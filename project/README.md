# Internal Linking Intelligence (Jev-powered)

An AI-assisted internal linking audit tool: crawl a site's sitemap, build a
graph of its existing internal links, flag orphan pages, and use Jev
(TypeSafe AI) to judge which pages *should* link to each other but don't —
rendered as an interactive graph an editor can actually act on.

Verified working end-to-end against a real, live site.

## Why Jev for this problem

Internal link auditing isn't a handful of decisions — it's thousands. A
60-page blog alone has on the order of 3,500 candidate page pairs if you
want to catch every real opportunity, not just the obvious ones. That's a
high-volume, well-defined judgment call (is page A relevant to page B, and
how), not a "write me an explanation" task.

Jev is TypeSafe's "System One" model: you hand it a `state` (page content,
here) plus typed questions — `Score` (rate against a rubric) or `Choice`
(classify from a fixed list) — and it returns a typed answer with a
probability and confidence, not generated prose. That fits this problem's
shape: no free text to parse, no inconsistent output format across
thousands of calls, and a confidence value that plugs straight into an
automation threshold.

This project treats that distinction literally in its architecture: Jev
supplies judgment (relevance score, relationship type, confidence); it
never touches page content directly and never writes a word of the
recommendation text — both are handled by plain code, on purpose.

## Architecture

```
sitemap.xml
    │
    ▼
sitemap_utils.py  (stdlib xml.etree.ElementTree only)
    │
    ├── parse sitemap / sitemap-index, recurse into child sitemaps
    ├── normalize URLs, dedupe, optional URL_INCLUDE_PATTERN filter
    ▼
page_fetch.py  (stdlib urllib + html.parser only)
    │
    ├── fetch + parse each page: title, h1/h2, links (nav/footer/sidebar/content), text
    ▼
pipeline.py
    ├── build_existing_link_graph()  -- networkx, contextual links only
    ├── detect_orphans()             -- not_analyzed vs no_incoming_contextual_links
    ├── _candidate_pairs()           -- same-site pairs without an existing link
    │
    ▼
jev_client.py  ── real typesafe-sdk, one system_one() call per candidate pair
    ├── Score question  -> relevance, normalized 0-1
    └── Choice question -> relationship_type (supporting/related/parent_child/comparison/not_relevant)
    │
    ▼
opportunity_text.py  -- assembles reason/anchor/context from page metadata (not Jev)
pipeline._cap_per_source()  -- keeps top MAX_OPPORTUNITIES_PER_SOURCE per page
    │
    ▼
visualize.py  -- interactive HTML (pyvis/vis.js)
    │
    ▼
data/output/
    ├── urls.json
    ├── page_analysis.json
    ├── existing_link_graph.json
    ├── orphan_pages.csv
    ├── internal_link_opportunities.csv
    ├── jev_errors.json         (if any Jev calls failed)
    └── site_link_graph.html
```

No database, no backend server, no crawling framework
(BeautifulSoup/Scrapy/Playwright/Puppeteer/`requests`-based scraping) — per
the project's own constraints. All intermediate state is plain JSON/CSV
files under `data/output/`.

## How the Jev decision layer actually works

For every candidate page pair, one `system_one` call asks two questions
against a `state` containing both pages' title/H1/content:

- **Score** — "how relevant is target_page as a link target from
  source_page's content", rated against a 4-point rubric (unrelated →
  clearly supports linking). `ScoreAnswer.score` is a probability-weighted
  average over the rubric's indices (e.g. 0-3, can fall between levels) —
  normalized to `relevance_score_normalized` (0-1) for comparability.
- **Choice** — classifies the relationship: `supporting`, `related`,
  `parent_child`, `comparison`, or `not_relevant`.

Both answers carry their own confidence (0-1). Two thresholds turn that
into a decision: `RELEVANCE_THRESHOLD` decides what's even worth
surfacing, and each opportunity's `confidence_label` (derived from the
lower of the two confidences) decides whether it's auto-suggested or
flagged `requires_editorial_review`.

**A real result from testing this on a live site:** on a blog where most
posts share a general topic, Jev correctly scored nearly every pair as
"related" — accurate, but useless if surfaced wholesale (exactly the
"excessive linking" this kind of tool needs to avoid). `_cap_per_source()`
keeps only the top `MAX_OPPORTUNITIES_PER_SOURCE` recommendations per page,
ranked by relevance then confidence, so output stays something an editor
can actually act on instead of a wall of true-but-unhelpful suggestions.

Jev never sees raw HTML (page_fetch.py extracts content first) and never
generates the `reason`/`recommended_anchor_text`/`suggested_context` text —
those are template-assembled from real page metadata in
`opportunity_text.py` and labeled `text_source="template"` vs
`score_source="jev"`, so the two are never conflated in the output.

## Status

Everything below is implemented, tested, and has run successfully against
a real, live site (not just synthetic data):

| Component | What it does |
|---|---|
| `sitemap_utils.py` | Sitemap/sitemap-index parsing, URL normalization, dedup, optional include-pattern filter |
| `page_fetch.py` | Single-page fetch + extraction (title, headings, links w/ location, text) — stdlib only |
| `pipeline.py` | Existing link graph, orphan detection, candidate-pair generation, per-source capping |
| `jev_client.py` | Real Jev integration (`typesafe-sdk` 0.7.0) — Score + Choice questions, concurrent, error-tolerant |
| `opportunity_text.py` | Template-assembled recommendation text (not model-generated) |
| `visualize.py` | Interactive HTML graph (pyvis/vis.js) with search/filter/details/export |
| `main.py` | Orchestrates the full run |

37 tests pass, no network required: `python3 -m pytest tests/`.

## A note on where this was built

Early development happened in a cloud sandbox whose egress policy blocked
essentially all outbound traffic except a small host allowlist (confirmed
directly via the proxy's own status endpoint, not assumed) — so the live
"real site + real Jev call" step couldn't run there. That's an artifact of
that specific environment, not a limitation of the project: run the same
code anywhere with normal outbound network access (a laptop, most CI) and
it works, which is exactly what happened once development moved to a
real machine — sitemap parsed, pages fetched, Jev calls succeeded,
recommendations generated, visualization rendered.

## Bugs found and fixed during live testing

Worth keeping visible since they were genuine bugs, not configuration
issues, caught only once this ran against a real environment:

- **Stale shell env vars silently winning over `.env`**: `load_dotenv()`
  defaults to `override=False`, so a variable already exported into a
  terminal session (e.g. by an editor's "inject .env into terminal"
  feature) stayed stuck even after `.env` was edited and saved. Fixed with
  `override=True` — `.env` is now always authoritative.
- **Malformed CDN stylesheet link**: pyvis 0.3.2 writes a doubled
  `dist/dist/vis-network.min.css` path (404s) plus a dead
  `../node_modules/vis/...` reference. Both stripped/corrected in
  `visualize.py`'s post-processing pass.
- **Graph that never stopped moving**: vis-network's `stabilization`
  option only fast-forwards the *initial* layout; physics otherwise runs
  forever. Added a `stabilizationIterationsDone` listener that disables
  physics once the layout settles.
- **Over-linking on topically narrow content**: see "How the Jev decision
  layer actually works" above — fixed with per-source capping.

## Running it

```bash
pip install -r requirements.txt
python3 -m pytest tests/   # 37 tests, no network required
python3 main.py            # sitemap -> fetch -> graph -> orphans -> opportunities -> visualization
```

Configure `.env`:
```
JEV_API_KEY=
JEV_API_BASE_URL=               # optional, defaults to https://api.typesafe.ai
JEV_MODEL=                       # optional, defaults to the SDK's own default (jev-latest)
WEBSITE_DOMAIN=
SITEMAP_PATH=                    # local file path or remote URL; follows sitemap-index files
VALIDATION_LIMIT=5               # how many sitemap URLs (after any filter) to process per run
URL_INCLUDE_PATTERN=             # optional substring filter, e.g. /blogs/
JEV_CONCURRENCY=5
RELEVANCE_THRESHOLD=0.5          # normalized 0-1 minimum to surface an opportunity
MAX_OPPORTUNITIES_PER_SOURCE=3   # cap recommendations per source page
```

Start small (`VALIDATION_LIMIT=5`) before scaling up — opportunity
detection evaluates roughly N×(N-1) candidate pairs, so cost and runtime
grow fast with page count. There's no candidate pre-filter yet (e.g.
cheap local similarity before spending a Jev call), which is the natural
next step before pointing this at a full sitemap of any real size.

Open `data/output/site_link_graph.html` in a browser afterward — solid
edges are existing links, dashed edges (colored by confidence) are
recommendations, red diamonds are orphans, gray triangles are sitemap URLs
not analyzed in that run. Search, filter by link type/confidence/section,
click anything for details, and export currently-visible recommendations
as CSV directly from the page.
