"""Entry point for the Internal Linking Intelligence pipeline.

Runs: sitemap ingestion -> page fetch -> existing link graph -> orphan
detection -> (if JEV_API_KEY is set) Jev-judged opportunity detection ->
interactive HTML visualization.
"""

import asyncio
import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import networkx as nx
from dotenv import load_dotenv

from pipeline import build_existing_link_graph, detect_orphans, fetch_pages, find_opportunities
from sitemap_utils import build_url_inventory, parse_sitemap
from visualize import build_visualization

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "output"

OPPORTUNITY_FIELDS = [
    "source_url", "source_title", "target_url", "target_title", "relationship_type",
    "relevance_score", "relevance_confidence", "confidence_label",
    "recommended_anchor_text", "suggested_context", "reason",
    "requires_editorial_review", "text_source", "score_source",
]


def load_config() -> dict:
    load_dotenv(BASE_DIR / ".env", override=True)
    config = {
        "jev_api_key": os.getenv("JEV_API_KEY"),
        "jev_api_base_url": os.getenv("JEV_API_BASE_URL"),
        "jev_model": os.getenv("JEV_MODEL"),
        "website_domain": os.getenv("WEBSITE_DOMAIN"),
        "sitemap_path": os.getenv("SITEMAP_PATH"),
        "validation_limit": int(os.getenv("VALIDATION_LIMIT", "5")),
        "url_include_pattern": os.getenv("URL_INCLUDE_PATTERN"),
        "jev_concurrency": int(os.getenv("JEV_CONCURRENCY", "5")),
        "relevance_threshold": float(os.getenv("RELEVANCE_THRESHOLD", "0.5")),
    }
    missing = [k for k in ("website_domain", "sitemap_path") if not config[k]]
    if missing:
        print(f"Missing required environment variables: {', '.join(m.upper() for m in missing)}")
        print("Set them in project/.env before running.")
    return config


def run_sitemap_ingestion(sitemap_path: str) -> list[dict]:
    entries, errors = parse_sitemap(sitemap_path)
    inventory = build_url_inventory(entries)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "urls.json", "w") as f:
        json.dump(inventory, f, indent=2)

    if errors:
        with open(OUTPUT_DIR / "sitemap_errors.json", "w") as f:
            json.dump(errors, f, indent=2)
        print(f"{len(errors)} sitemap source(s) failed to parse -- see data/output/sitemap_errors.json")

    print(f"Wrote {len(inventory)} URL(s) to data/output/urls.json")
    return inventory


def main() -> None:
    config = load_config()

    if not config["sitemap_path"]:
        print("SITEMAP_PATH is not set. Nothing to do.")
        sys.exit(1)

    inventory = run_sitemap_ingestion(config["sitemap_path"])

    pattern = config["url_include_pattern"]
    if pattern:
        before = len(inventory)
        inventory = [entry for entry in inventory if pattern in entry["url"]]
        print(f"URL_INCLUDE_PATTERN={pattern!r} matched {len(inventory)}/{before} sitemap URL(s)")

    limit = config["validation_limit"]
    target_urls = [entry["url"] for entry in inventory[:limit]]
    print(f"\nFetching {len(target_urls)} page(s) for this run (VALIDATION_LIMIT={limit})...")

    pages = fetch_pages(target_urls)
    for url, page in pages.items():
        print(f"  {url} -> {'OK' if not page.error else 'ERROR: ' + page.error}")

    graph = build_existing_link_graph(pages)
    orphans = detect_orphans(target_urls, pages, graph)

    with open(OUTPUT_DIR / "page_analysis.json", "w") as f:
        json.dump(
            {
                url: {
                    "title": page.title,
                    "h1": page.h1,
                    "h2": page.h2,
                    "word_count": len(page.text.split()),
                    "http_status": page.http_status,
                    "error": page.error,
                    "links": [asdict(link) for link in page.links],
                }
                for url, page in pages.items()
            },
            f,
            indent=2,
        )
    with open(OUTPUT_DIR / "existing_link_graph.json", "w") as f:
        json.dump(nx.node_link_data(graph), f, indent=2)
    with open(OUTPUT_DIR / "orphan_pages.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "status", "reason", "title"])
        writer.writeheader()
        for orphan in orphans:
            writer.writerow({"url": orphan["url"], "status": orphan["status"],
                              "reason": orphan.get("reason", ""), "title": orphan.get("title", "")})

    print(f"\nExisting link graph: {graph.number_of_nodes()} node(s), {graph.number_of_edges()} edge(s)")
    print(f"Orphan / not-analyzed pages: {len(orphans)} -- see data/output/orphan_pages.csv")

    opportunities, errors = [], []
    if config["jev_api_key"]:
        print("\nRunning Jev-powered opportunity detection...")
        opportunities, errors = asyncio.run(find_opportunities(
            pages, graph,
            api_key=config["jev_api_key"],
            base_url=config["jev_api_base_url"],
            model=config["jev_model"],
            concurrency=config["jev_concurrency"],
            relevance_threshold=config["relevance_threshold"],
        ))

        with open(OUTPUT_DIR / "internal_link_opportunities.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=OPPORTUNITY_FIELDS)
            writer.writeheader()
            for opp in opportunities:
                writer.writerow(asdict(opp))

        if errors:
            with open(OUTPUT_DIR / "jev_errors.json", "w") as f:
                json.dump([asdict(err) for err in errors], f, indent=2)

        print(f"Found {len(opportunities)} opportunit(y/ies) -- data/output/internal_link_opportunities.csv")
        if errors:
            print(f"{len(errors)} Jev call(s) failed -- see data/output/jev_errors.json")
    else:
        print("\nJEV_API_KEY not set -- skipping opportunity detection (graph/orphans still visualized).")

    viz_path = OUTPUT_DIR / "site_link_graph.html"
    build_visualization(pages, graph, opportunities, orphans, str(viz_path))
    print(f"\nInteractive visualization written to {viz_path}")


if __name__ == "__main__":
    main()
