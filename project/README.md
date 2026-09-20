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
| 2. Sitemap processing | Done — `sitemap_utils.py` |
| 3. Page content extraction | Done — `page_fetch.py` (stdlib `urllib` + `html.parser` only) |
| 3. Jev-powered page-pair judgment | Done — `jev_client.py`, real `typesafe-sdk` 0.7.0 | 
| 4. Existing link graph + orphan detection | Done — `pipeline.py` (networkx) |
| 6. Opportunity text assembly | Done — `opportunity_text.py` |
| Live end-to-end run (real site + real Jev call) | **Cannot run from this sandbox** — see below |
| 7. Interactive visualization | Done — `visualize.py` (pyvis/vis.js), demo at `data/output/site_link_graph.html` via `demo_visualization.py` |

31 tests pass: `python3 -m pytest tests/`.

## Jev — verified capabilities (confirmed against real docs + the installed SDK)

- `system_one(state, questions)` evaluates a `state` (text/JSON/array) the
  caller supplies against named `Noul`/`Choice`/`Score` questions, returning
  typed answers — never free text. Installed `typesafe-sdk==0.7.0`'s public
  API matches the docs exactly (checked directly against the installed
  classes).
- **Jev cannot fetch a URL itself.** That's why `page_fetch.py` exists: a
  minimal, stdlib-only single-page fetcher (no BeautifulSoup/Scrapy/
  Playwright/Puppeteer/`requests`), used to turn each sitemap URL into text
  before Jev ever sees it.
- **Jev cannot generate free text.** `reason`, `recommended_anchor_text`,
  and `suggested_context` are assembled from extracted page metadata by
  `opportunity_text.py`, not by Jev — every opportunity carries
  `text_source="template"` and `score_source="jev"` so the two are never
  conflated.
- `ScoreAnswer.score` is a probability-weighted average over an **ordered
  rubric's indices** (e.g. 0-3 for a 4-item rubric, can fall between
  levels) — not a 0-1 similarity value. `jev_client.py` normalizes it to
  `relevance_score_normalized` (0-1) for comparability.
- No documented multi-state batch endpoint: one call judges one page pair
  (several questions per call, in parallel). Analyzing many pairs means many
  concurrent calls (`AsyncTypeSafeClient`, bounded by `JEV_CONCURRENCY`).
  `RetryPolicy` already retries 408/429/5xx with backoff, so `jev_client.py`
  leans on that instead of reimplementing it; a failure on one pair is
  captured as a `JevJudgmentError` rather than aborting the whole batch.
- Pricing isn't documented anywhere verified. Each response's `usage`
  (input/output token counts) is surfaced instead of assuming a $/token
  figure, so real cost can be tracked empirically.

## Live end-to-end run — cannot execute from this sandbox

This session's outbound network goes through an org-level egress proxy that
allow-lists specific hosts (package registries, Anthropic's own API, etc.)
and denies everything else. This was confirmed directly, not assumed —
`curl -sS $HTTPS_PROXY/__agentproxy/status` shows explicit `403` policy
denials for both:

- `example.com:443` (a stand-in test fetch)
- `api.typesafe.ai:443` (Jev's real API host)

Per that proxy's own operating instructions: a 403/407 here means "not
allowed by your organization's egress policy for this session... do not
retry or route around it." So even with a real `JEV_API_KEY`, this sandbox
cannot make the live call, and it cannot fetch pages from a real website
either.

**What this means practically:** the code is written and tested against
real interfaces — `jev_client.py`'s tests construct actual
`typesafe_sdk.ScoreAnswer`/`ChoiceAnswer`/`SystemOneResponse` objects (the
installed package's own classes) as fixtures, not hand-rolled guesses — but
the Phase 3/10 "test with 5 real URLs" step needs to run somewhere with
outbound network access to both the target site and `api.typesafe.ai`:
your own machine, or a CI/cloud environment without this restriction.
There's no API key that fixes this from here.

## Visualization (Phase 7)

`visualize.py` renders `data/output/site_link_graph.html` — an interactive
vis.js network graph with a control panel (search, filter by link type /
confidence / section, orphan-only toggle, click-for-details, CSV export of
currently-visible recommendations). It's generated automatically at the end
of `main.py`.

Node color/grouping ("Section") is a **heuristic** derived from each URL's
first path segment (e.g. `/blog/...` -> `blog`) — there is no topic-
clustering step in this pipeline, so this is deliberately not labeled
"Topic" in the UI to avoid overclaiming a capability that wasn't built.

Since live crawling can't run from this sandbox, `demo_visualization.py`
generates the same visualization from synthetic sample data so its actual
behavior can be reviewed before a real run. It's not part of the pipeline
or test suite.

## Running what exists today

```
pip install -r requirements.txt
python3 -m pytest tests/   # 31 tests, no network required
python3 main.py            # sitemap -> fetch -> graph -> orphans -> (if JEV_API_KEY set) opportunities
```

Configure `project/.env`:
```
JEV_API_KEY=
JEV_API_BASE_URL=       # optional, defaults to https://api.typesafe.ai
JEV_MODEL=               # optional, defaults to the SDK's own default (jev-latest)
WEBSITE_DOMAIN=
SITEMAP_PATH=
VALIDATION_LIMIT=5       # how many sitemap URLs to process per run
JEV_CONCURRENCY=5
RELEVANCE_THRESHOLD=0.5  # normalized 0-1 minimum to surface an opportunity
MAX_OPPORTUNITIES_PER_SOURCE=3  # cap recommendations per source page (avoids "excessive linking")
URL_INCLUDE_PATTERN=      # optional substring filter on the sitemap inventory, e.g. /blogs/
```
`SITEMAP_PATH` accepts a local file path or a remote URL, and follows
sitemap-index files recursively. Outputs land in `data/output/`:
`urls.json`, `page_analysis.json`, `existing_link_graph.json`,
`orphan_pages.csv`, and — once Jev runs — `internal_link_opportunities.csv`
(plus `jev_errors.json` for any failed calls).
