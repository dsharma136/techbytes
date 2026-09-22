"""Run all scrapers and write combined output — smoke test for the data pipeline."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scrapers.arxiv_scraper import fetch_arxiv_articles
from scrapers.brave_scraper import fetch_brave_articles
from scrapers.hn_scraper import fetch_hn_articles
from scrapers.schema import validate_articles

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main() -> None:
    print("🔍 AI Pulse Scrapers — Fetching tech news...")
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}\n")

    t0 = time.perf_counter()

    hn_task = fetch_hn_articles(scrape_pages=True)
    arxiv_task = fetch_arxiv_articles()
    brave_task = fetch_brave_articles(scrape_pages=True)

    hn_articles, brave_articles = await asyncio.gather(hn_task, brave_task)
    arxiv_articles = await arxiv_task

    all_articles = hn_articles + arxiv_articles + brave_articles
    valid, errors = validate_articles(all_articles)

    print("—" * 60)
    print("SUMMARY")
    print(f"  HackerNews:  {len(hn_articles)} articles")
    print(f"  ArXiv:       {len(arxiv_articles)} articles")
    print(f"  Brave News:  {len(brave_articles)} articles")
    print(f"  Combined:    {len(all_articles)} articles")
    print(f"  Valid:       {len(valid)} | Validation errors: {len(errors)}")
    if errors:
        for e in errors[:10]:
            print(f"    ⚠️  {e}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
    print()

    hn_by_points = sorted(
        [a for a in hn_articles if a.engagement],
        key=lambda a: int(a.engagement["points"]),
        reverse=True,
    )[:5]
    print("Top 5 HackerNews (by points):")
    for i, a in enumerate(hn_by_points, 1):
        pts = a.engagement["points"] if a.engagement else 0
        print(f"  {i}. [{pts}↑] {a.title}")
    print()

    print("Sample ArXiv papers:")
    for a in arxiv_articles[:5]:
        print(f"  • {a.title}")
    if not arxiv_articles:
        print("  (none)")
    print()

    print("Sample Brave News:")
    for a in brave_articles[:5]:
        print(f"  • {a.title}")
    if not brave_articles:
        print("  (none)")
    print()

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    out_path = out_dir / f"all_articles_{day}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([a.to_dict() for a in all_articles], f, indent=2, ensure_ascii=False)
    print(f"Saved: {out_path}")

    elapsed = time.perf_counter() - t0
    print(f"\nTotal execution time: {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
