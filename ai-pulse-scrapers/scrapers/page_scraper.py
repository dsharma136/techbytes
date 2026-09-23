"""Fetch and extract main text + metadata from HTML pages (shared by scrapers)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def clean_text(text: str) -> str:
    """Collapse whitespace, strip ends, truncate to 3000 characters."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:3000]


def _error_result(url: str, exc: BaseException) -> dict[str, Any]:
    return {
        "url": url,
        "title": None,
        "meta_description": None,
        "main_text": None,
        "og_image": None,
        "error": str(exc),
    }


async def scrape_page(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """
    Fetch HTML and extract title, description, main text, and og:image.
    Never raises; returns ``error`` string on failure.
    """
    try:
        async with httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")

        for tag_name in ("script", "style", "nav", "footer", "header", "aside", "form"):
            for el in soup.find_all(tag_name):
                el.decompose()

        title_el = soup.title
        title = title_el.get_text(strip=True) if title_el else ""

        meta_desc_el = soup.find("meta", attrs={"name": "description"})
        if meta_desc_el is None:
            meta_desc_el = soup.find("meta", attrs={"name": "Description"})
        meta_description = ""
        if meta_desc_el is not None:
            content = meta_desc_el.get("content")
            meta_description = content.strip() if content else ""

        og_el = soup.find("meta", property="og:image")
        og_image: str | None = None
        if og_el is not None:
            content = og_el.get("content")
            if content:
                og_image = content.strip()

        body = soup.body
        if body is not None:
            raw_body_text = body.get_text(separator=" ")
        else:
            raw_body_text = soup.get_text(separator=" ")

        main_text = clean_text(raw_body_text)

        return {
            "url": url,
            "title": title or None,
            "meta_description": meta_description or None,
            "main_text": main_text or None,
            "og_image": og_image,
            "error": None,
        }
    except httpx.HTTPStatusError as e:
        code = e.response.status_code if e.response is not None else None
        if code in (403, 404):
            # Many publishers block bots; expected noise, keep logs short.
            logger.info("scrape_page %s for %s (blocked or missing)", code, url)
        else:
            logger.warning("scrape_page HTTP %s for %s", code, url)
        return _error_result(url, e)
    except Exception as e:
        msg = str(e)
        if "403" in msg or "404" in msg:
            logger.info("scrape_page blocked/missing for %s", url)
        else:
            logger.warning("scrape_page failed for %s: %s", url, e)
        return _error_result(url, e)


async def scrape_multiple(urls: list[str], max_concurrent: int = 3) -> list[dict[str, Any]]:
    """Scrape URLs with bounded concurrency; results match input order."""
    if not urls:
        return []

    sem = asyncio.Semaphore(max_concurrent)

    async def _one(u: str) -> dict[str, Any]:
        async with sem:
            return await scrape_page(u)

    return await asyncio.gather(*(_one(u) for u in urls))


if __name__ == "__main__":
    import asyncio, sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com"
    result = asyncio.run(scrape_page(url))
    print(json.dumps(result, indent=2))
