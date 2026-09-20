"""Minimal single-page content extraction: stdlib urllib + html.parser only.

This exists because Jev cannot retrieve page content itself (see
jev_client.py) -- something has to turn a sitemap URL into text before Jev
can evaluate it. This is deliberately NOT a crawling framework: it fetches
exactly the URL it's given, once, and does not discover or follow links on
its own. No BeautifulSoup, Scrapy, Playwright, Puppeteer, or `requests`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

NAV_LIKE_TAGS = {"nav", "footer", "aside", "header"}
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template"}

_robots_cache: dict[str, robotparser.RobotFileParser] = {}


@dataclass
class ExtractedLink:
    href: str
    anchor_text: str
    location: str  # "nav" | "footer" | "sidebar" | "content"


@dataclass
class ExtractedPage:
    url: str
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    h1: str | None = None
    h2: list[str] = field(default_factory=list)
    text: str = ""
    links: list[ExtractedLink] = field(default_factory=list)
    error: str | None = None


class _PageHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.tag_stack: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta_description: str | None = None
        self.canonical_url: str | None = None
        self.h1: str | None = None
        self.h2: list[str] = []
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []
        self._text_chunks: list[str] = []
        self.links: list[ExtractedLink] = []
        self._link_href: str | None = None
        self._link_text_buf: list[str] = []

    def _location(self) -> str:
        stack_set = set(self.tag_stack)
        if "nav" in stack_set or "header" in stack_set:
            return "nav"
        if "footer" in stack_set:
            return "footer"
        if "aside" in stack_set:
            return "sidebar"
        return "content"

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.tag_stack.append(tag)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            if (attrs_dict.get("name") or "").lower() == "description" and attrs_dict.get("content"):
                self.meta_description = attrs_dict["content"].strip()
        elif tag == "link":
            if (attrs_dict.get("rel") or "").lower() == "canonical" and attrs_dict.get("href"):
                self.canonical_url = urljoin(self.base_url, attrs_dict["href"])
        elif tag in ("h1", "h2"):
            self._heading_tag = tag
            self._heading_buf = []
        elif tag == "a" and attrs_dict.get("href"):
            self._link_href = urljoin(self.base_url, attrs_dict["href"])
            self._link_text_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2") and self._heading_tag == tag:
            text = " ".join("".join(self._heading_buf).split())
            if text:
                if tag == "h1" and self.h1 is None:
                    self.h1 = text
                else:
                    self.h2.append(text)
            self._heading_tag = None
        elif tag == "a" and self._link_href is not None:
            anchor_text = " ".join("".join(self._link_text_buf).split())
            self.links.append(ExtractedLink(href=self._link_href, anchor_text=anchor_text, location=self._location()))
            self._link_href = None

        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()
        elif tag in self.tag_stack:
            # tolerate real-world HTML with mismatched/unclosed tags
            idx = len(self.tag_stack) - 1 - self.tag_stack[::-1].index(tag)
            del self.tag_stack[idx]

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        if self._heading_tag is not None:
            self._heading_buf.append(data)
        if self._link_href is not None:
            self._link_text_buf.append(data)
        if set(self.tag_stack) & SKIP_TEXT_TAGS:
            return
        if self._location() == "content":
            stripped = data.strip()
            if stripped:
                self._text_chunks.append(stripped)

    @property
    def title(self) -> str | None:
        text = " ".join("".join(self._title_parts).split())
        return text or None

    @property
    def text(self) -> str:
        return " ".join(self._text_chunks)


def parse_html(html: str, url: str) -> ExtractedPage:
    parser = _PageHTMLParser(base_url=url)
    parser.feed(html)
    return ExtractedPage(
        url=url,
        title=parser.title,
        meta_description=parser.meta_description,
        canonical_url=parser.canonical_url,
        h1=parser.h1,
        h2=parser.h2,
        text=parser.text,
        links=parser.links,
    )


def _robots_allows(url: str, user_agent: str, timeout: float) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(origin, "/robots.txt"))
        try:
            req = Request(rp.url, headers={"User-Agent": user_agent})
            with urlopen(req, timeout=timeout) as resp:
                rp.parse(resp.read().decode("utf-8", errors="replace").splitlines())
        except (HTTPError, URLError, OSError):
            rp.allow_all = True  # no robots.txt reachable -> treat as unrestricted
        _robots_cache[origin] = rp
    return rp.can_fetch(user_agent, url)


def fetch_page(url: str, timeout: float = 15.0, user_agent: str = "InternalLinkingIntelligence/1.0") -> ExtractedPage:
    """Fetch and parse a single URL. Never raises: failures come back as an
    ExtractedPage with `error` set and no content, so a bad page doesn't
    stop the run."""
    if not _robots_allows(url, user_agent, timeout):
        return ExtractedPage(url=url, error="disallowed_by_robots_txt")

    try:
        req = Request(url, headers={"User-Agent": user_agent})
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            final_url = resp.geturl()
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            body = resp.read()
    except HTTPError as exc:
        return ExtractedPage(url=url, http_status=exc.code, error=f"http_error:{exc.code}")
    except URLError as exc:
        return ExtractedPage(url=url, error=f"connection_error:{exc.reason}")
    except OSError as exc:
        return ExtractedPage(url=url, error=f"connection_error:{exc}")

    if content_type and content_type != "text/html":
        return ExtractedPage(
            url=url, final_url=final_url, http_status=status, content_type=content_type,
            error="non_html_content",
        )

    page = parse_html(body.decode("utf-8", errors="replace"), final_url)
    page.final_url = final_url
    page.http_status = status
    page.content_type = content_type or "text/html"
    return page
