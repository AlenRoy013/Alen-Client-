import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opportunity_text import LinkOpportunity  # noqa: E402
from page_fetch import ExtractedPage  # noqa: E402
from pipeline import build_existing_link_graph  # noqa: E402
from visualize import build_visualization, url_section  # noqa: E402

A, B, C = "https://example.com/blog/a", "https://example.com/pricing", "https://example.com/blog/orphan"


def test_url_section_handles_root_and_nested_paths():
    assert url_section("https://example.com/") == "home"
    assert url_section("https://example.com") == "home"
    assert url_section("https://example.com/pricing") == "pricing"
    assert url_section("https://example.com/blog/post/deep") == "blog"


def _page(url, links=None, title=None, text="content " * 20):
    return ExtractedPage(url=url, final_url=url, http_status=200, title=title or url, text=text, links=links or [])


def make_opportunity(source, target, confidence="high", relationship="supporting", score=0.8):
    return LinkOpportunity(
        source_url=source, source_title="Source", target_url=target, target_title="Target",
        relationship_type=relationship, relevance_score=score, relevance_confidence=0.9,
        confidence_label=confidence, recommended_anchor_text="target anchor",
        suggested_context="Add a link here.", reason="Because reasons.",
        requires_editorial_review=(confidence == "low"),
    )


def test_build_visualization_writes_html_with_panel_and_graph_data(tmp_path):
    pages = {A: _page(A), B: _page(B), C: _page(C)}
    graph = build_existing_link_graph(pages)  # no links -> B and C both orphaned relative to A
    orphans = [
        {"url": C, "status": "no_incoming_contextual_links", "title": "orphan"},
    ]
    opportunities = [make_opportunity(A, B, confidence="high")]

    output_path = tmp_path / "site_link_graph.html"
    build_visualization(pages, graph, opportunities, orphans, str(output_path))

    html_doc = output_path.read_text(encoding="utf-8")

    # control panel injected
    assert 'id="ili-panel"' in html_doc
    assert 'id="ili-search"' in html_doc
    assert 'id="ili-export-btn"' in html_doc

    # nodes carry our custom metadata
    assert '"urlFull": "' + A + '"' in html_doc
    assert '"isOrphan": true' in html_doc  # C is orphaned
    assert '"section": "blog"' in html_doc
    assert '"section": "pricing"' in html_doc

    # recommended edge present with dashed styling and confidence label
    assert '"linkType": "recommended"' in html_doc
    assert '"confidenceLabel": "high"' in html_doc
    assert '"dashes": true' in html_doc


def test_opportunities_to_pages_outside_graph_are_skipped(tmp_path):
    pages = {A: _page(A)}
    graph = build_existing_link_graph(pages)
    opportunities = [make_opportunity(A, "https://example.com/not-fetched")]

    output_path = tmp_path / "graph.html"
    build_visualization(pages, graph, opportunities, [], str(output_path))

    html_doc = output_path.read_text(encoding="utf-8")
    assert "not-fetched" not in html_doc
