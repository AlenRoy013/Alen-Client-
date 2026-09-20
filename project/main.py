"""Entry point for the Internal Linking Intelligence pipeline.

Phases 1-2 (env setup, sitemap ingestion) run today. Phase 3+ (Jev-powered
analysis, link graph, opportunities, visualization) are blocked pending
verification of Jev's real API -- see README.md.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from sitemap_utils import build_url_inventory, parse_sitemap

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "output"


def load_config() -> dict:
    load_dotenv(BASE_DIR / ".env")
    config = {
        "jev_api_key": os.getenv("JEV_API_KEY"),
        "jev_api_base_url": os.getenv("JEV_API_BASE_URL"),
        "website_domain": os.getenv("WEBSITE_DOMAIN"),
        "sitemap_path": os.getenv("SITEMAP_PATH"),
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

    if not config["jev_api_key"]:
        print("\nJEV_API_KEY not set -- stopping after Phase 2 (sitemap ingestion).")
        return

    from jev_client import JevNotVerifiedError, analyze_pages

    try:
        analyze_pages(inventory, config["jev_api_key"], config["jev_api_base_url"] or "")
    except JevNotVerifiedError as exc:
        print(f"\nStopping before Phase 3: {exc}")
        sys.exit(2)


if __name__ == "__main__":
    main()
