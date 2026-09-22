"""Full Phase 1 pipeline: scrape → cluster → write cards (one command, end-to-end)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from llm.processor import cluster_articles, generate_cards
from scrapers.arxiv_scraper import fetch_arxiv_articles
from scrapers.brave_scraper import fetch_brave_articles
from scrapers.hn_scraper import fetch_hn_articles
from scrapers.schema import validate_articles

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main() -> None:
    start = time.time()

    # Step 1: Scrape
    print("📡 Step 1/3: Scraping sources...")
    hn_articles, brave_articles = await asyncio.gather(
        fetch_hn_articles(scrape_pages=True),
        fetch_brave_articles(scrape_pages=True),
    )
    arxiv_articles = await fetch_arxiv_articles()
    all_articles = hn_articles + arxiv_articles + brave_articles
    valid, errors = validate_articles(all_articles)
    print(
        f"   Found {len(valid)} valid articles ({len(hn_articles)} HN, {len(arxiv_articles)} ArXiv, {len(brave_articles)} Brave)"
    )

    # Step 2: Cluster
    print("🧠 Step 2/3: Clustering articles...")
    clusters, working = await cluster_articles(
        valid, target_clusters=min(50, len(valid)) if valid else 0
    )
    print(f"   Created {len(clusters)} story clusters")

    # Step 3: Generate cards (indices in clusters refer to `working`, not full `valid`)
    print("✍️  Step 3/3: Writing cards...")
    cards = await generate_cards(clusters, working)
    print(f"   Generated {len(cards)} cards")

    # Output
    print(f"\n{'=' * 60}")
    print("📰 AI PULSE — Daily Tech Briefing")
    print(f"{'=' * 60}\n")

    for i, card in enumerate(cards):
        cat = card.get("category", "general").upper().replace("_", " ")
        print(f"Card {i + 1} [{cat}]")
        print(f"  {card['headline']}")
        print(f"  {card['blurb']}")
        print(f"  💡 {card['why_it_matters']}")
        print()

    # Save everything
    output = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "total_articles_scraped": len(all_articles),
        "valid_articles": len(valid),
        "clusters": len(clusters),
        "cards": cards,
        "errors": errors,
        "pipeline_time_seconds": round(time.time() - start, 1),
    }
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_file = out_dir / f"pipeline_{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n⏱️  Total pipeline time: {output['pipeline_time_seconds']}s")
    print(f"💾 Full output saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
