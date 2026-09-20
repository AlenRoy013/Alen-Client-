import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from page_fetch import parse_html  # noqa: E402

SAMPLE_HTML = """
<html>
<head>
  <title>Sales Commission Calculation Guide</title>
  <meta name="description" content="Learn how to calculate sales commission.">
  <link rel="canonical" href="/blog/sales-commission-calculation">
</head>
<body>
  <header><nav><a href="/">Home</a><a href="/pricing">Pricing</a></nav></header>
  <main>
    <h1>Sales Commission Calculation</h1>
    <p>Manually tracking commissions is error-prone. Consider
       <a href="/sales-commission-software">sales commission software</a> instead.</p>
    <h2>Common Pitfalls</h2>
    <p>Spreadsheets don't scale.</p>
  </main>
  <aside><a href="/related-post">Related post</a></aside>
  <footer><a href="/privacy">Privacy</a></footer>
  <script>var x = "ignored";</script>
</body>
</html>
"""


def test_extracts_title_meta_canonical_and_headings():
    page = parse_html(SAMPLE_HTML, "https://example.com/blog/sales-commission-calculation")
    assert page.title == "Sales Commission Calculation Guide"
    assert page.meta_description == "Learn how to calculate sales commission."
    assert page.canonical_url == "https://example.com/blog/sales-commission-calculation"
    assert page.h1 == "Sales Commission Calculation"
    assert page.h2 == ["Common Pitfalls"]


def test_classifies_link_locations():
    page = parse_html(SAMPLE_HTML, "https://example.com/blog/sales-commission-calculation")
    by_href = {link.href: link for link in page.links}
    assert by_href["https://example.com/"].location == "nav"
    assert by_href["https://example.com/pricing"].location == "nav"
    assert by_href["https://example.com/related-post"].location == "sidebar"
    assert by_href["https://example.com/privacy"].location == "footer"
    assert by_href["https://example.com/sales-commission-software"].location == "content"


def test_content_text_excludes_nav_footer_and_scripts():
    page = parse_html(SAMPLE_HTML, "https://example.com/page")
    assert "ignored" not in page.text
    assert "Home" not in page.text
    assert "Privacy" not in page.text
    assert "Manually tracking commissions" in page.text


def test_anchor_text_is_extracted_and_whitespace_normalized():
    html = '<body><p>See <a href="/target">  sales   commission\nsoftware </a></p></body>'
    page = parse_html(html, "https://example.com/")
    assert page.links[0].anchor_text == "sales commission software"


def test_resolves_relative_hrefs_against_base_url():
    html = '<body><a href="../pricing">Pricing</a></body>'
    page = parse_html(html, "https://example.com/blog/post")
    assert page.links[0].href == "https://example.com/pricing"


def test_first_h1_wins_when_multiple_present():
    html = "<body><h1>First</h1><h1>Second</h1></body>"
    page = parse_html(html, "https://example.com/")
    assert page.h1 == "First"
