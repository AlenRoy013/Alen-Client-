import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opportunity_text import LinkOpportunity  # noqa: E402
from page_fetch import ExtractedLink, ExtractedPage  # noqa: E402
from pipeline import _candidate_pairs, _cap_per_source, build_existing_link_graph, detect_orphans  # noqa: E402

A, B, C = "https://example.com/a", "https://example.com/b", "https://example.com/c"


def opportunity(source, target, score, confidence=0.9):
    return LinkOpportunity(
        source_url=source, source_title="S", target_url=target, target_title="T",
        relationship_type="related", relevance_score=score, relevance_confidence=confidence,
        confidence_label="high", recommended_anchor_text="anchor", suggested_context="ctx",
        reason="reason", requires_editorial_review=False,
    )


def page(url, links=None, error=None, title=None, text="some content here"):
    return ExtractedPage(url=url, final_url=url, http_status=200, title=title, text=text,
                          links=links or [], error=error)


def test_graph_only_counts_contextual_links_as_edges():
    pages = {
        A: page(A, links=[
            ExtractedLink(href=B, anchor_text="see b", location="content"),
            ExtractedLink(href=C, anchor_text="nav c", location="nav"),
        ]),
        B: page(B),
        C: page(C),
    }
    graph = build_existing_link_graph(pages)
    assert graph.has_edge(A, B)
    assert not graph.has_edge(A, C)  # nav link, not contextual


def test_graph_excludes_links_to_pages_outside_fetched_set():
    pages = {A: page(A, links=[ExtractedLink(href="https://example.com/not-fetched", anchor_text="x", location="content")])}
    graph = build_existing_link_graph(pages)
    assert graph.number_of_edges() == 0


def test_orphan_with_zero_incoming_contextual_links():
    pages = {A: page(A, links=[]), B: page(B)}
    graph = build_existing_link_graph(pages)
    orphans = detect_orphans([A, B], pages, graph)
    statuses = {o["url"]: o["status"] for o in orphans}
    assert statuses[A] == "no_incoming_contextual_links"
    assert statuses[B] == "no_incoming_contextual_links"


def test_page_with_incoming_link_is_not_orphan():
    pages = {
        A: page(A, links=[ExtractedLink(href=B, anchor_text="b", location="content")]),
        B: page(B),
    }
    graph = build_existing_link_graph(pages)
    orphans = detect_orphans([A, B], pages, graph)
    assert B not in {o["url"] for o in orphans}


def test_failed_fetch_is_not_analyzed_not_a_confirmed_orphan():
    pages = {A: page(A, error="http_error:404")}
    graph = build_existing_link_graph(pages)
    orphans = detect_orphans([A], pages, graph)
    assert orphans == [{"url": A, "status": "not_analyzed", "reason": "http_error:404"}]


def test_candidate_pairs_excludes_pages_with_existing_contextual_link():
    pages = {
        A: page(A, links=[ExtractedLink(href=B, anchor_text="b", location="content")]),
        B: page(B),
    }
    graph = build_existing_link_graph(pages)
    pairs = _candidate_pairs(pages, graph)
    pair_urls = [(s["url"], t["url"]) for s, t in pairs]
    assert (A, B) not in pair_urls  # already linked
    assert (B, A) in pair_urls      # reverse direction still a candidate


def test_candidate_pairs_excludes_failed_fetches():
    pages = {A: page(A), B: page(B, error="non_html_content")}
    graph = build_existing_link_graph(pages)
    pairs = _candidate_pairs(pages, graph)
    assert pairs == []


def test_cap_per_source_keeps_strongest_n_by_relevance():
    opps = [
        opportunity(A, "t1", score=0.9),
        opportunity(A, "t2", score=0.95),
        opportunity(A, "t3", score=0.5),
        opportunity(A, "t4", score=0.7),
    ]
    kept = _cap_per_source(opps, max_per_source=2)
    assert [o.target_url for o in kept] == ["t2", "t1"]


def test_cap_per_source_is_independent_per_source_page():
    opps = [opportunity(A, "t1", score=0.9), opportunity(B, "t2", score=0.8)]
    kept = _cap_per_source(opps, max_per_source=1)
    assert len(kept) == 2


def test_cap_per_source_zero_disables_all_recommendations():
    kept = _cap_per_source([opportunity(A, "t1", score=0.9)], max_per_source=0)
    assert kept == []
