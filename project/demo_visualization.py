"""Generates a demo site_link_graph.html from synthetic data.

Not part of the pipeline or test suite -- this exists only because live
crawling and live Jev calls are blocked from this sandbox (see README), so
this is how the visualization's actual look gets demonstrated before a real
run happens on a machine with normal network access.
"""

from pathlib import Path

from opportunity_text import LinkOpportunity
from page_fetch import ExtractedLink, ExtractedPage
from pipeline import build_existing_link_graph, detect_orphans
from visualize import build_visualization

BASE = "https://example.com"
HOME = f"{BASE}/"
COMMISSION_CALC = f"{BASE}/blog/sales-commission-calculation"
COMMISSION_SOFTWARE = f"{BASE}/sales-commission-software"
PRICING = f"{BASE}/pricing"
ORPHAN_POST = f"{BASE}/blog/forgotten-post"
NOT_FETCHED = f"{BASE}/blog/timed-out-page"

pages = {
    HOME: ExtractedPage(
        url=HOME, final_url=HOME, http_status=200, title="Example Co - Sales Commission Tools",
        text="Example Co helps sales teams manage commissions and quotas. " * 15,
        links=[
            ExtractedLink(href=COMMISSION_CALC, anchor_text="commission calculation guide", location="content"),
            ExtractedLink(href=PRICING, anchor_text="Pricing", location="nav"),
        ],
    ),
    COMMISSION_CALC: ExtractedPage(
        url=COMMISSION_CALC, final_url=COMMISSION_CALC, http_status=200,
        title="Sales Commission Calculation Guide",
        text=(
            "Manually tracking commissions in spreadsheets is error-prone and slow. "
            "Most teams eventually look for a better way to calculate variable pay. " * 10
        ),
        links=[ExtractedLink(href=HOME, anchor_text="Home", location="nav")],
    ),
    COMMISSION_SOFTWARE: ExtractedPage(
        url=COMMISSION_SOFTWARE, final_url=COMMISSION_SOFTWARE, http_status=200,
        title="Sales Commission Software",
        text="Automate commission calculations with Example Co's platform. " * 12,
        links=[ExtractedLink(href=PRICING, anchor_text="Pricing", location="nav")],
    ),
    PRICING: ExtractedPage(
        url=PRICING, final_url=PRICING, http_status=200, title="Pricing",
        text="Plans for every team size. " * 8,
        links=[ExtractedLink(href=HOME, anchor_text="Home", location="footer")],
    ),
    ORPHAN_POST: ExtractedPage(
        url=ORPHAN_POST, final_url=ORPHAN_POST, http_status=200, title="A Forgotten Blog Post",
        text="This post exists in the sitemap but nothing links to it. " * 10,
        links=[],
    ),
}

target_urls = list(pages.keys()) + [NOT_FETCHED]
pages_with_missing = dict(pages)
pages_with_missing[NOT_FETCHED] = ExtractedPage(url=NOT_FETCHED, error="connection_error:timed out")

graph = build_existing_link_graph(pages)
orphans = detect_orphans(target_urls, pages_with_missing, graph)

opportunities = [
    LinkOpportunity(
        source_url=COMMISSION_CALC, source_title="Sales Commission Calculation Guide",
        target_url=COMMISSION_SOFTWARE, target_title="Sales Commission Software",
        relationship_type="supporting", relevance_score=0.92, relevance_confidence=0.88,
        confidence_label="high", recommended_anchor_text="Sales Commission Software",
        suggested_context="Add a contextual link to Sales Commission Software where Sales Commission Calculation Guide discusses related content.",
        reason="Sales Commission Software provides supporting detail for a claim made in Sales Commission Calculation Guide.",
        requires_editorial_review=False,
    ),
    LinkOpportunity(
        source_url=PRICING, source_title="Pricing",
        target_url=COMMISSION_SOFTWARE, target_title="Sales Commission Software",
        relationship_type="related", relevance_score=0.58, relevance_confidence=0.55,
        confidence_label="medium", recommended_anchor_text="Sales Commission Software",
        suggested_context="Add a contextual link to Sales Commission Software where Pricing discusses related content.",
        reason="Pricing and Sales Commission Software cover closely related topics with no existing link between them.",
        requires_editorial_review=False,
    ),
    LinkOpportunity(
        source_url=HOME, source_title="Example Co - Sales Commission Tools",
        target_url=ORPHAN_POST, target_title="A Forgotten Blog Post",
        relationship_type="related", relevance_score=0.42, relevance_confidence=0.4,
        confidence_label="low", recommended_anchor_text="A Forgotten Blog Post",
        suggested_context="Add a contextual link to A Forgotten Blog Post where Example Co - Sales Commission Tools discusses related content.",
        reason="Example Co - Sales Commission Tools and A Forgotten Blog Post cover closely related topics with no existing link between them.",
        requires_editorial_review=True,
    ),
]

output_path = Path(__file__).parent / "data" / "output" / "site_link_graph.html"
build_visualization(pages, graph, opportunities, orphans, str(output_path))
print(f"wrote {output_path}")
