"""Phase 2: sitemap ingestion. Stdlib XML parsing only, no crawling framework."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from urllib.request import urlopen, Request

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid",
}


@dataclass
class SitemapEntry:
    url: str
    raw_url: str
    last_modified: str | None
    source: str


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _read_source(source: str) -> bytes:
    """Read a sitemap from a local file path or a remote URL."""
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        req = Request(source, headers={"User-Agent": "InternalLinkingIntelligence/1.0"})
        with urlopen(req, timeout=15) as resp:
            return resp.read()
    with open(source, "rb") as f:
        return f.read()


def normalize_url(url: str) -> str:
    """Canonicalize a URL: lowercase scheme/host, strip default port, drop fragment
    and known tracking params, sort remaining query params, strip trailing slash."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[: -len(":80")]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[: -len(":443")]

    path = re.sub(r"/{2,}", "/", parsed.path) or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept_params = sorted(
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in TRACKING_PARAMS
    )
    query = urlencode(kept_params)

    return urlunparse((scheme, netloc, path, "", query, ""))


def _parse_urlset(root: ET.Element, source: str) -> list[SitemapEntry]:
    entries = []
    for url_el in root:
        if _strip_namespace(url_el.tag) != "url":
            continue
        loc, lastmod = None, None
        for child in url_el:
            tag = _strip_namespace(child.tag)
            if tag == "loc" and child.text:
                loc = child.text.strip()
            elif tag == "lastmod" and child.text:
                lastmod = child.text.strip()
        if loc:
            entries.append(SitemapEntry(url=normalize_url(loc), raw_url=loc, last_modified=lastmod, source=source))
    return entries


def _parse_sitemapindex(root: ET.Element) -> list[str]:
    child_urls = []
    for sitemap_el in root:
        if _strip_namespace(sitemap_el.tag) != "sitemap":
            continue
        for child in sitemap_el:
            if _strip_namespace(child.tag) == "loc" and child.text:
                child_urls.append(child.text.strip())
    return child_urls


def parse_sitemap(source: str, _seen_sources: set[str] | None = None) -> tuple[list[SitemapEntry], list[dict]]:
    """Parse a sitemap or sitemap-index (local path or URL), recursing into child
    sitemaps. Returns (entries, errors); never raises on a single bad/unreachable
    child sitemap so the rest of the tree can still be processed."""
    seen = _seen_sources or set()
    entries: list[SitemapEntry] = []
    errors: list[dict] = []

    if source in seen:
        return entries, errors
    seen.add(source)

    try:
        raw = _read_source(source)
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        errors.append({"source": source, "error": str(exc)})
        return entries, errors

    root_tag = _strip_namespace(root.tag)
    if root_tag == "urlset":
        entries.extend(_parse_urlset(root, source))
    elif root_tag == "sitemapindex":
        for child_url in _parse_sitemapindex(root):
            child_entries, child_errors = parse_sitemap(child_url, seen)
            entries.extend(child_entries)
            errors.extend(child_errors)
    else:
        errors.append({"source": source, "error": f"unrecognized root element <{root_tag}>"})

    return entries, errors


def build_url_inventory(entries: list[SitemapEntry]) -> list[dict]:
    """Dedupe by normalized URL. When duplicates exist, keep the entry with a
    last_modified date if one is available; first-seen wins otherwise."""
    by_url: dict[str, SitemapEntry] = {}
    for entry in entries:
        existing = by_url.get(entry.url)
        if existing is None:
            by_url[entry.url] = entry
        elif existing.last_modified is None and entry.last_modified is not None:
            by_url[entry.url] = entry

    return [
        {"url": e.url, "last_modified": e.last_modified, "source": e.source}
        for e in by_url.values()
    ]
