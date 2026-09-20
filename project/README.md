# Internal Linking Intelligence (Jev-powered)

## Architecture

```
sitemap.xml
    │
    ▼
sitemap_utils.py  (stdlib xml.etree.ElementTree only)
    │
    ├── parse sitemap / sitemap-index, recurse into child sitemaps
    ├── normalize URLs, dedupe
    ▼
data/output/urls.json
    │
    ▼
jev_client.py  ── BLOCKED, see below
    │
    ▼ (once unblocked)
main.py / graph + viz modules (not yet written)
    ├── build existing link graph (networkx)
    ├── identify new linking opportunities
    ├── detect orphans
    └── render interactive HTML (pyvis)
    │
    ▼
data/output/
    ├── urls.json
    ├── existing_link_graph.json
    ├── internal_link_opportunities.csv
    ├── orphan_pages.csv
    └── site_link_graph.html
```

No database, no backend server, no custom web-crawling framework
(BeautifulSoup/Scrapy/Playwright/Puppeteer/requests-based scraping) —
per project constraints. Intermediate state is JSON files under
`data/output/`.

## Status

| Phase | Status |
|---|---|
| 1. Environment setup | Done |
| 2. Sitemap processing | Done — `sitemap_utils.py`, 9 passing tests in `tests/` |
| 3. Jev-powered page analysis | **Blocked** — see below |
| 4+. Link graph, opportunities, orphans, visualization | Not started (depend on Phase 3) |

## Jev verification status — blocked

This project's own rule is: *do not assume Jev's API capabilities or invent
endpoint syntax.* That rule could not be satisfied yet:

- Direct fetches from this environment to `docs.typesafe.ai`,
  `docs.aimlapi.com`, `www.langchain.com`, `pydantic.dev`, and
  `developers.cloudflare.com` all failed with `EGRESS_BLOCKED` — this
  sandbox's network proxy does not allow reaching any of them.
- A web-search summarizer (the only external-info tool that worked) returned
  two descriptions of "Jev by TypeSafe AI" that **contradict each other**:
  one gave the endpoint as `https://api.aimlapi.com/v1/decisions` with
  `pip install typesafe-sdk`; the other gave `POST https://api.typesafe.ai/v1/systemone`
  with an unspecified SDK and a waitlist-gated access model. Neither could be
  cross-checked against a primary source.

Writing `jev_client.py` against either would mean guessing request/response
syntax and silently risking fabricated results in every phase downstream of
it (topics, relationships, anchor text) — which is exactly what this project
forbids. `jev_client.py` currently raises `JevNotVerifiedError` with this
explanation instead of calling anything.

**One open question also needs an answer before Phase 3 can be designed
correctly, not just implemented:** every unverified description found calls
Jev a "System One" **decision model** — it evaluates a "state" you give it
against typed questions (yes/no, choice, score) and returns calibrated
answers. Nothing found describes it as a web-browsing/retrieval agent. If
that's accurate, Jev cannot fetch a URL's content by itself — something has
to extract page content and hand it to Jev as input. That would conflict
with the constraint banning all standard HTTP-fetch/parsing libraries,
since *some* minimal content-retrieval step becomes unavoidable no matter
what it's called. This needs your call, not a silent workaround.

### To unblock

Provide one of:
1. The raw text (or a pasted excerpt) of Jev's actual API reference —
   auth, endpoint(s), request/response schema, batch support, rate limits.
2. A `curl`/Python example you've already run successfully against it.
3. Confirmation of whether Jev can retrieve page content from a URL itself,
   or only evaluate content it's given.

Once any of these lands, `jev_client.py` gets implemented against it, and
Phases 4-9 (graph, opportunities, orphans, clusters, visualization) proceed
on top of the same `data/output/urls.json` already being produced.

## Running what exists today

```
pip install -r requirements.txt
python3 main.py          # runs Phase 1-2, writes data/output/urls.json
python3 -m pytest tests/ # 9 tests covering sitemap parsing edge cases
```

Configure `project/.env`:
```
JEV_API_KEY=
WEBSITE_DOMAIN=
SITEMAP_PATH=
```
`SITEMAP_PATH` accepts a local file path or a remote URL, and follows
sitemap-index files recursively.
