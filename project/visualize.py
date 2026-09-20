"""Phase 7: interactive HTML visualization.

Built on pyvis (vis.js): pyvis renders the base network, and this module
appends a control panel (search, filters, click-for-details, CSV export) as
extra HTML/JS injected before </body>, since pyvis's own template doesn't
expose those controls. Confirmed empirically (not assumed) that pyvis's
generated `nodes`/`edges`/`network`/`allNodes`/`allEdges` JS variables are
plain globals inside a non-wrapped <script> tag, and that arbitrary custom
fields passed to add_node/add_edge survive into the DataSet JSON -- both
checked directly against the installed pyvis output before relying on them.

Node color/grouping uses "section": a heuristic derived from each URL's
first path segment (e.g. "/blog/..." -> "blog"). This is NOT a Jev-derived
topic cluster -- no topic-clustering step exists in this pipeline -- so the
panel labels it "Section", not "Topic", to avoid overclaiming.
"""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

import networkx as nx
from pyvis.network import Network

from opportunity_text import LinkOpportunity
from page_fetch import ExtractedPage

PALETTE = ["#0173B2", "#DE8F05", "#029E73", "#D55E00", "#CC78BC", "#CA9161", "#ECE133", "#56B4E9"]
ORPHAN_BORDER = "#D62728"
NOT_ANALYZED_COLOR = "#CCCCCC"
CONFIDENCE_COLOR = {"high": "#029E73", "medium": "#DE8F05", "low": "#949494"}
EXISTING_EDGE_COLOR = "#666666"


def url_section(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[0] if path else "home"


def _section_color(section: str, sections_order: list[str]) -> str:
    if section not in sections_order:
        return "#999999"
    return PALETTE[sections_order.index(section) % len(PALETTE)]


def build_visualization(
    pages: dict[str, ExtractedPage],
    graph: nx.DiGraph,
    opportunities: list[LinkOpportunity],
    orphans: list[dict],
    output_path: str,
) -> None:
    orphan_urls = {o["url"] for o in orphans if o["status"] == "no_incoming_contextual_links"}
    not_analyzed = {o["url"]: o.get("reason") for o in orphans if o["status"] == "not_analyzed"}

    sections = sorted({url_section(u) for u in graph.nodes})

    net = Network(height="760px", width="100%", directed=True, bgcolor="#ffffff", font_color="#222222",
                  cdn_resources="remote")
    net.barnes_hut(gravity=-4000, spring_length=140, spring_strength=0.02, damping=0.5)

    for url in graph.nodes:
        page = pages.get(url)
        section = url_section(url)
        is_orphan = url in orphan_urls
        title = (page.title if page else None) or url
        in_deg, out_deg = graph.in_degree(url), graph.out_degree(url)
        word_count = len(page.text.split()) if page else 0
        short_label = title if len(title) <= 40 else title[:37] + "..."

        net.add_node(
            url,
            label=short_label,
            title=html.escape(f"{title}\n{url}\nIn: {in_deg}  Out: {out_deg}  Words: {word_count}"),
            shape="diamond" if is_orphan else "dot",
            size=12 + min(in_deg, 10) * 2,
            color={"background": _section_color(section, sections), "border": ORPHAN_BORDER if is_orphan else "#333333"},
            borderWidth=3 if is_orphan else 1,
            section=section, isOrphan=is_orphan, isNotAnalyzed=False, pageTitle=title,
            inDegree=in_deg, outDegree=out_deg, wordCount=word_count, urlFull=url,
        )

    # Sitemap URLs that weren't successfully fetched/analyzed: shown as ghost
    # nodes so they read as visible gaps rather than silently disappearing.
    for url, reason in not_analyzed.items():
        if url in graph.nodes:
            continue
        short_label = (url.rstrip("/").rsplit("/", 1)[-1] or url)[:37]
        net.add_node(
            url,
            label=short_label,
            title=html.escape(f"Not analyzed this run: {reason}\n{url}"),
            shape="triangle",
            color={"background": NOT_ANALYZED_COLOR, "border": "#999999"},
            size=10,
            section="not_analyzed", isOrphan=False, isNotAnalyzed=True, pageTitle=url,
            inDegree=0, outDegree=0, wordCount=0, urlFull=url,
        )

    edge_id = 0
    for source, target, data in graph.edges(data=True):
        anchor = data.get("anchor_text") or ""
        net.add_edge(
            source, target,
            id=f"existing-{edge_id}",
            color=EXISTING_EDGE_COLOR, dashes=False, arrows="to",
            title=html.escape(f"Existing link\nAnchor: {anchor}"),
            linkType="existing", anchorText=anchor,
            relationshipType="", confidenceLabel="", relevanceScore="",
            recommendedAnchorText="", suggestedContext="", reason="", requiresReview=False,
        )
        edge_id += 1

    for opp in opportunities:
        if opp.source_url not in graph.nodes or opp.target_url not in graph.nodes:
            continue
        color = CONFIDENCE_COLOR.get(opp.confidence_label, "#949494")
        net.add_edge(
            opp.source_url, opp.target_url,
            id=f"opp-{edge_id}",
            color=color, dashes=True, arrows="to",
            label=opp.relationship_type,
            title=html.escape(
                f"Recommended ({opp.confidence_label} confidence)\n"
                f"Relationship: {opp.relationship_type}\nAnchor: {opp.recommended_anchor_text}"
            ),
            linkType="recommended", anchorText="",
            relationshipType=opp.relationship_type,
            confidenceLabel=opp.confidence_label,
            relevanceScore=round(opp.relevance_score, 3),
            recommendedAnchorText=opp.recommended_anchor_text,
            suggestedContext=opp.suggested_context,
            reason=opp.reason,
            requiresReview=opp.requires_editorial_review,
        )
        edge_id += 1

    net.set_options(json.dumps({
        "interaction": {"hover": True, "tooltipDelay": 100},
        "physics": {"stabilization": {"iterations": 300}},
    }))

    net.write_html(output_path, notebook=False)
    _inject_controls(output_path, sections)


def _inject_controls(path: str, sections: list[str]) -> None:
    with open(path, "r", encoding="utf-8") as f:
        doc = f.read()

    section_options = "".join(f'<option value="{s}">{s}</option>' for s in sections)
    panel = _PANEL_HTML.replace("{{SECTION_OPTIONS}}", section_options)

    doc = doc.replace(
        '<div id="mynetwork" class="card-body"></div>',
        '<div id="mynetwork" class="card-body"></div>' + panel,
        1,
    )
    doc = doc.replace("</body>", _PANEL_SCRIPT + "\n</body>", 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


_PANEL_HTML = """
<style>
  #ili-panel { position: fixed; top: 12px; right: 12px; width: 320px; max-height: 92vh; overflow-y: auto;
    background: #ffffffee; border: 1px solid #ccc; border-radius: 8px; padding: 14px;
    font-family: system-ui, -apple-system, sans-serif; font-size: 13px; z-index: 1000;
    box-shadow: 0 2px 10px rgba(0,0,0,0.15); }
  #ili-panel h3 { margin: 0 0 8px; font-size: 15px; }
  #ili-panel h4 { margin: 14px 0 4px; font-size: 12px; text-transform: uppercase; color: #666; }
  #ili-panel label { display:block; margin-top:10px; font-weight:600; }
  #ili-panel input[type=text], #ili-panel select { width:100%; box-sizing:border-box; margin-top:4px; padding:5px; }
  #ili-panel input[type=checkbox] { width:auto; display:inline-block; margin-right:6px; }
  .ili-legend-item { display:flex; align-items:center; gap:8px; margin-top:5px; }
  .ili-swatch { width:16px; height:0; display:inline-block; border-top-width:3px; border-top-style:solid; }
  .ili-swatch-node { width:12px; height:12px; border-radius:50%; display:inline-block; }
  #ili-details { margin-top:10px; padding-top:10px; border-top:1px solid #ddd; line-height:1.5; }
  .ili-field-label { font-weight:600; }
  #ili-panel button { margin-top:8px; width:100%; padding:7px; cursor:pointer; border:1px solid #ccc;
    border-radius:4px; background:#f5f5f5; }
  #ili-panel button:hover { background:#eaeaea; }
</style>
<div id="ili-panel">
  <h3>Internal Linking Intelligence</h3>

  <label for="ili-search">Search (title or URL)</label>
  <input type="text" id="ili-search" placeholder="Type to filter...">

  <label for="ili-linktype">Link type</label>
  <select id="ili-linktype">
    <option value="all">All</option>
    <option value="existing">Existing only</option>
    <option value="recommended">Recommended only</option>
  </select>

  <label for="ili-confidence">Recommendation confidence</label>
  <select id="ili-confidence">
    <option value="all">All</option>
    <option value="high">High</option>
    <option value="medium">Medium</option>
    <option value="low">Low</option>
  </select>

  <label for="ili-section">Section (heuristic, from URL path)</label>
  <select id="ili-section">
    <option value="all">All</option>
    {{SECTION_OPTIONS}}
  </select>

  <label><input type="checkbox" id="ili-orphans-only">Orphan pages only</label>

  <button id="ili-reset-btn">Reset filters</button>
  <button id="ili-export-btn">Export visible recommendations (CSV)</button>

  <h4>Legend</h4>
  <div class="ili-legend-item"><span class="ili-swatch" style="border-color:#666;"></span> Existing link (solid)</div>
  <div class="ili-legend-item"><span class="ili-swatch" style="border-color:#029E73; border-top-style:dashed;"></span> Recommended, high confidence</div>
  <div class="ili-legend-item"><span class="ili-swatch" style="border-color:#DE8F05; border-top-style:dashed;"></span> Recommended, medium confidence</div>
  <div class="ili-legend-item"><span class="ili-swatch" style="border-color:#949494; border-top-style:dashed;"></span> Recommended, low confidence</div>
  <div class="ili-legend-item"><span class="ili-swatch-node" style="background:#fff; border:3px solid #D62728;"></span> Orphan page (diamond)</div>
  <div class="ili-legend-item"><span class="ili-swatch-node" style="background:#ccc; border:1px solid #999; border-radius:2px;"></span> Not analyzed this run (triangle)</div>

  <div id="ili-details"><em>Click a page or a link for details.</em></div>
</div>
"""

_PANEL_SCRIPT = """
<script type="text/javascript">
(function () {
  function esc(s) {
    var d = document.createElement('div');
    d.innerText = (s === undefined || s === null) ? '' : String(s);
    return d.innerHTML;
  }

  function renderNodeDetails(n) {
    var out = '';
    out += '<div><span class="ili-field-label">Page:</span> ' + esc(n.pageTitle) + '</div>';
    out += '<div><span class="ili-field-label">URL:</span> ' + esc(n.urlFull) + '</div>';
    out += '<div><span class="ili-field-label">Section:</span> ' + esc(n.section) + '</div>';
    out += '<div><span class="ili-field-label">Inbound / outbound links:</span> ' + n.inDegree + ' / ' + n.outDegree + '</div>';
    out += '<div><span class="ili-field-label">Word count:</span> ' + n.wordCount + '</div>';
    if (n.isOrphan) out += '<div style="color:#D62728;">No incoming contextual links (orphan)</div>';
    if (n.isNotAnalyzed) out += '<div style="color:#888;">Not analyzed in this run</div>';
    return out;
  }

  function renderEdgeDetails(e) {
    if (e.linkType === 'existing') {
      return '<div><span class="ili-field-label">Existing link</span></div>' +
        '<div><span class="ili-field-label">From:</span> ' + esc(e.from) + '</div>' +
        '<div><span class="ili-field-label">To:</span> ' + esc(e.to) + '</div>' +
        '<div><span class="ili-field-label">Anchor text:</span> ' + esc(e.anchorText || '(none)') + '</div>';
    }
    var out = '<div><span class="ili-field-label">Recommended link</span> (' + esc(e.confidenceLabel) + ' confidence)</div>';
    out += '<div><span class="ili-field-label">From:</span> ' + esc(e.from) + '</div>';
    out += '<div><span class="ili-field-label">To:</span> ' + esc(e.to) + '</div>';
    out += '<div><span class="ili-field-label">Relationship:</span> ' + esc(e.relationshipType) + '</div>';
    out += '<div><span class="ili-field-label">Relevance (Jev, normalized 0-1):</span> ' + esc(e.relevanceScore) + '</div>';
    out += '<div><span class="ili-field-label">Recommended anchor:</span> ' + esc(e.recommendedAnchorText) + '</div>';
    out += '<div><span class="ili-field-label">Suggested context:</span> ' + esc(e.suggestedContext) + '</div>';
    out += '<div><span class="ili-field-label">Reason:</span> ' + esc(e.reason) + '</div>';
    if (e.requiresReview) out += '<div style="color:#DE8F05;">Flagged for editorial review (low confidence)</div>';
    out += '<div style="color:#888; font-size:11px; margin-top:4px;">Relevance/relationship come from Jev. Reason/anchor/context are template-generated from page metadata, not written by Jev.</div>';
    return out;
  }

  network.on('click', function (params) {
    var detailsDiv = document.getElementById('ili-details');
    if (params.nodes.length > 0) {
      detailsDiv.innerHTML = renderNodeDetails(allNodes[params.nodes[0]]);
    } else if (params.edges.length > 0) {
      detailsDiv.innerHTML = renderEdgeDetails(allEdges[params.edges[0]]);
    }
  });

  function applyFilters() {
    var searchTerm = document.getElementById('ili-search').value.trim().toLowerCase();
    var linkTypeSel = document.getElementById('ili-linktype').value;
    var confidenceSel = document.getElementById('ili-confidence').value;
    var sectionSel = document.getElementById('ili-section').value;
    var orphansOnly = document.getElementById('ili-orphans-only').checked;

    var nodeUpdates = [];
    Object.keys(allNodes).forEach(function (id) {
      var n = allNodes[id];
      var hidden = false;
      if (searchTerm &&
          (n.pageTitle || '').toLowerCase().indexOf(searchTerm) < 0 &&
          (n.urlFull || '').toLowerCase().indexOf(searchTerm) < 0) {
        hidden = true;
      }
      if (sectionSel !== 'all' && n.section !== sectionSel) hidden = true;
      if (orphansOnly && !n.isOrphan) hidden = true;
      nodeUpdates.push({ id: id, hidden: hidden });
    });
    nodes.update(nodeUpdates);

    var edgeUpdates = [];
    Object.keys(allEdges).forEach(function (id) {
      var e = allEdges[id];
      var hidden = false;
      if (linkTypeSel !== 'all' && e.linkType !== linkTypeSel) hidden = true;
      if (e.linkType === 'recommended' && confidenceSel !== 'all' && e.confidenceLabel !== confidenceSel) hidden = true;
      edgeUpdates.push({ id: id, hidden: hidden });
    });
    edges.update(edgeUpdates);
  }

  ['ili-search', 'ili-linktype', 'ili-confidence', 'ili-section'].forEach(function (id) {
    var el = document.getElementById(id);
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  });
  document.getElementById('ili-orphans-only').addEventListener('change', applyFilters);

  document.getElementById('ili-reset-btn').addEventListener('click', function () {
    document.getElementById('ili-search').value = '';
    document.getElementById('ili-linktype').value = 'all';
    document.getElementById('ili-confidence').value = 'all';
    document.getElementById('ili-section').value = 'all';
    document.getElementById('ili-orphans-only').checked = false;
    applyFilters();
  });

  document.getElementById('ili-export-btn').addEventListener('click', function () {
    var rows = [['source_url', 'target_url', 'relationship_type', 'confidence', 'relevance_score',
                 'recommended_anchor_text', 'suggested_context', 'reason']];
    Object.keys(allEdges).forEach(function (id) {
      var e = allEdges[id];
      if (e.linkType !== 'recommended') return;
      var current = edges.get(id);
      if (current && current.hidden) return;
      rows.push([e.from, e.to, e.relationshipType, e.confidenceLabel, e.relevanceScore,
                 e.recommendedAnchorText, e.suggestedContext, e.reason]);
    });
    var csv = rows.map(function (r) {
      return r.map(function (v) { return '"' + String(v === undefined ? '' : v).replace(/"/g, '""') + '"'; }).join(',');
    }).join('\\n');
    var blob = new Blob([csv], { type: 'text/csv' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'internal_link_opportunities_filtered.csv';
    link.click();
  });
})();
</script>
"""
