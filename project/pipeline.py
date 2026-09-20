"""Orchestrates sitemap -> fetch -> existing-link graph -> orphan detection
-> (optional) Jev-judged opportunities, for a bounded validation run."""

from __future__ import annotations

import itertools
from urllib.parse import urlparse

import networkx as nx

from jev_client import JevJudgmentError, judge_pairs
from opportunity_text import LinkOpportunity, build_opportunity
from page_fetch import ExtractedPage, fetch_page


def fetch_pages(urls: list[str], timeout: float = 15.0) -> dict[str, ExtractedPage]:
    return {url: fetch_page(url, timeout=timeout) for url in urls}


def build_existing_link_graph(pages: dict[str, ExtractedPage]) -> nx.DiGraph:
    """Nodes = successfully fetched pages. Edges = contextual (location ==
    "content") links between two pages that are both in this fetched set --
    nav/footer/sidebar links are deliberately excluded, per the project's
    "don't treat template links as contextual opportunities" rule."""
    graph = nx.DiGraph()
    for url, page in pages.items():
        if page.error:
            continue
        graph.add_node(url, title=page.title, h1=page.h1, word_count=len(page.text.split()))

    for url, page in pages.items():
        if page.error:
            continue
        for link in page.links:
            if link.location != "content":
                continue
            target = link.href.split("#")[0]
            if target != "/" :
                target = target.rstrip("/")
            if target in graph.nodes and target != url:
                graph.add_edge(url, target, anchor_text=link.anchor_text, location=link.location)
    return graph


def detect_orphans(inventory_urls: list[str], pages: dict[str, ExtractedPage], graph: nx.DiGraph) -> list[dict]:
    """Two distinct orphan states, not conflated:
    - "not_analyzed": the URL wasn't successfully fetched in this run (crawl
      error, robots disallow, non-HTML) -- NOT a confirmed orphan.
    - "no_incoming_contextual_links": fetched successfully, present in the
      graph, and has zero inbound contextual-link edges from other fetched
      pages. This is only reliable across the set of pages actually fetched
      in this run -- see the caveat in README for whole-site runs.
    """
    orphans = []
    for url in inventory_urls:
        page = pages.get(url)
        if page is None or page.error:
            orphans.append({"url": url, "status": "not_analyzed", "reason": (page.error if page else "not_fetched")})
            continue
        if url in graph.nodes and graph.in_degree(url) == 0:
            orphans.append({"url": url, "status": "no_incoming_contextual_links", "title": page.title})
    return orphans


def _candidate_pairs(pages: dict[str, ExtractedPage], graph: nx.DiGraph) -> list[tuple[dict, dict]]:
    """All same-site ordered pairs among successfully fetched pages that
    don't already have a contextual link between them. Fine for a small
    validation run; whole-site scale needs a cheap local pre-filter (e.g.
    TF-IDF similarity) before spending Jev calls on every pair -- see
    README cost-control notes."""
    ok_urls = [u for u, p in pages.items() if not p.error]
    pairs = []
    for source_url, target_url in itertools.permutations(ok_urls, 2):
        if graph.has_edge(source_url, target_url):
            continue
        source_page, target_page = pages[source_url], pages[target_url]
        pairs.append((
            {"url": source_url, "title": source_page.title, "h1": source_page.h1, "text": source_page.text},
            {"url": target_url, "title": target_page.title, "h1": target_page.h1, "text": target_page.text},
        ))
    return pairs


async def find_opportunities(
    pages: dict[str, ExtractedPage],
    graph: nx.DiGraph,
    api_key: str,
    base_url: str | None,
    model: str | None,
    concurrency: int,
    relevance_threshold: float,
    max_per_source: int = 3,
) -> tuple[list[LinkOpportunity], list[JevJudgmentError]]:
    pairs = _candidate_pairs(pages, graph)
    if not pairs:
        return [], []

    judgments = await judge_pairs(pairs, api_key=api_key, base_url=base_url, model=model, concurrency=concurrency)

    opportunities: list[LinkOpportunity] = []
    errors: list[JevJudgmentError] = []
    meta_by_url = {u: {"title": p.title, "h1": p.h1} for u, p in pages.items()}

    for judgment in judgments:
        if isinstance(judgment, JevJudgmentError):
            errors.append(judgment)
            continue
        opp = build_opportunity(
            judgment,
            meta_by_url.get(judgment.source_url, {}),
            meta_by_url.get(judgment.target_url, {}),
            relevance_threshold=relevance_threshold,
        )
        if opp is not None:
            opportunities.append(opp)

    return _cap_per_source(opportunities, max_per_source), errors


def _cap_per_source(opportunities: list[LinkOpportunity], max_per_source: int) -> list[LinkOpportunity]:
    """Keep only the strongest few recommendations per source page. Without
    this, a page topically similar to many others (common in a niche blog)
    gets recommended a link to nearly every one of them -- exactly the
    "excessive linking" this project's own rules rule out, and it makes the
    graph an unreadable tangle for no practical benefit."""
    by_source: dict[str, list[LinkOpportunity]] = {}
    for opp in opportunities:
        by_source.setdefault(opp.source_url, []).append(opp)

    kept = []
    for source_opps in by_source.values():
        source_opps.sort(key=lambda o: (o.relevance_score, o.relevance_confidence), reverse=True)
        kept.extend(source_opps[:max_per_source])
    return kept
