import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitemap_utils import build_url_inventory, normalize_url, parse_sitemap  # noqa: E402


def write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def test_normalize_url_strips_trailing_slash_and_tracking_params():
    assert normalize_url("https://Example.com/Blog/Post/?utm_source=x&b=2&a=1") == (
        "https://example.com/Blog/Post?a=1&b=2"
    )


def test_normalize_url_keeps_root_slash():
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_normalize_url_drops_default_port_and_fragment():
    assert normalize_url("https://example.com:443/page#section") == "https://example.com/page"


def test_parse_simple_urlset(tmp_path):
    sitemap = write(
        tmp_path,
        "sitemap.xml",
        """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/a</loc><lastmod>2026-08-01</lastmod></url>
          <url><loc>https://example.com/b/</loc></url>
        </urlset>""",
    )
    entries, errors = parse_sitemap(sitemap)
    assert errors == []
    assert len(entries) == 2
    assert entries[0].url == "https://example.com/a"
    assert entries[0].last_modified == "2026-08-01"
    assert entries[1].url == "https://example.com/b"


def test_parse_sitemap_index_recurses_into_children(tmp_path):
    child = write(
        tmp_path,
        "child.xml",
        """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/child-page</loc></url>
        </urlset>""",
    )
    index = write(
        tmp_path,
        "index.xml",
        f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{child}</loc></sitemap>
        </sitemapindex>""",
    )
    entries, errors = parse_sitemap(index)
    assert errors == []
    assert len(entries) == 1
    assert entries[0].url == "https://example.com/child-page"
    assert entries[0].source == child


def test_duplicate_urls_are_deduped_preferring_lastmod(tmp_path):
    sitemap = write(
        tmp_path,
        "dupes.xml",
        """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/dup/</loc></url>
          <url><loc>https://example.com/dup</loc><lastmod>2026-01-01</lastmod></url>
        </urlset>""",
    )
    entries, _ = parse_sitemap(sitemap)
    inventory = build_url_inventory(entries)
    assert len(inventory) == 1
    assert inventory[0]["last_modified"] == "2026-01-01"


def test_malformed_sitemap_reports_error_instead_of_raising(tmp_path):
    sitemap = write(tmp_path, "bad.xml", "<urlset><url><loc>not closed")
    entries, errors = parse_sitemap(sitemap)
    assert entries == []
    assert len(errors) == 1
    assert "bad.xml" in errors[0]["source"]


def test_missing_sitemap_file_reports_error_instead_of_raising():
    entries, errors = parse_sitemap("/nonexistent/path/sitemap.xml")
    assert entries == []
    assert len(errors) == 1


def test_unrelated_xml_root_reports_error(tmp_path):
    sitemap = write(tmp_path, "rss.xml", "<rss><channel></channel></rss>")
    entries, errors = parse_sitemap(sitemap)
    assert entries == []
    assert "unrecognized root element" in errors[0]["error"]
