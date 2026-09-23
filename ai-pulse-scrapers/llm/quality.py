"""Offline content-quality heuristics for TechBytes cards and clusters.

Used by the publish path (cheap filters, no extra LLM calls) and by
``scripts/verify_pipeline.py --fixture`` to flag production-feed problems.
"""

from __future__ import annotations

import re
from typing import Any

from .quotas import GENERAL_SLUG, TOPIC_CATEGORY_SLUGS
from .sources import extract_domain, significant_tokens

# Cap sources attached to a published card.
MAX_SOURCES_PER_CARD = 4

# Category definitions (also mirrored in clustering/card prompts).
CATEGORY_DEFS: dict[str, str] = {
    "ai_ml": (
        "AI/ML models, labs, research, agents, generative AI product launches, "
        "training/inference advances (OpenAI, Anthropic, Google DeepMind, Meta AI)."
    ),
    "chips_hardware": (
        "Semiconductors, GPUs/CPUs/accelerators, foundries, silicon, memory, "
        "chip export controls, hardware design (NVIDIA, AMD, TSMC, Intel, Apple silicon)."
    ),
    "networking_cloud": (
        "Cloud platforms, data centers, CDN, telecom/5G, networking gear, "
        "Kubernetes/infra platforms (AWS, Azure, Cloudflare, Cisco)."
    ),
    "cybersecurity": (
        "Breaches, ransomware, CVEs, APT campaigns, security products, privacy "
        "exploits, defensive security research."
    ),
    "autonomous_vehicles": (
        "Robotaxis, self-driving cars/trucks, AV software stacks, lidar/perception, "
        "delivery robots, consumer/commercial drones, AV regulation, vehicle cybersecurity."
    ),
}

CATEGORY_EXAMPLES: dict[str, tuple[str, ...]] = {
    "ai_ml": (
        "OpenAI releases a new model",
        "Anthropic changes Claude rate limits",
        "Google DeepMind publishes an AI paper",
    ),
    "chips_hardware": (
        "TSMC expands 2nm capacity",
        "NVIDIA launches a new GPU",
        "AMD discloses a CPU security erratum that is chip-specific",
    ),
    "networking_cloud": (
        "AWS outage in us-east-1",
        "Cloudflare rolls out a new CDN feature",
        "Cisco ships a new switch line",
    ),
    "cybersecurity": (
        "SolarWinds customers hit by a new campaign",
        "Critical CVE in enterprise VPN",
        "Chinese APT targets telecom networks",
    ),
    "autonomous_vehicles": (
        "Waymo expands robotaxi service",
        "FCC updates DJI drone rules",
        "BYD EV fleet remote-hack research",
    ),
}

# Strong keyword cues per topic (weighted loosely by presence).
_CATEGORY_CUES: dict[str, tuple[str, ...]] = {
    "ai_ml": (
        "openai",
        "anthropic",
        "claude",
        "chatgpt",
        "gpt",
        "llm",
        "deepmind",
        "gemini",
        "machine learning",
        "generative ai",
        "foundation model",
        "gitlab duo",
        "copilot",
        "ai model",
        "transformer",
        "inference",
        "training run",
        "chatgpt",
        "tracking cookie",
        "super intelligence",
        "apple intelligence",
        "ios ads",
        "persistent ads",
    ),
    "chips_hardware": (
        "nvidia",
        "amd",
        "tsmc",
        "semiconductor",
        "gpu",
        "hbm",
        "foundry",
        "wafer",
        "chip design",
        "apple silicon",
        "intel arc",
        "process node",
        "asic",
        "fpga",
    ),
    "networking_cloud": (
        "aws",
        "azure",
        "cloudflare",
        "data center",
        "kubernetes",
        "5g",
        "telecom",
        "cdn",
        "vpc",
        "cisco",
        "arista",
        "cloud outage",
        "s3",
        "ec2",
    ),
    "cybersecurity": (
        "ransomware",
        "breach",
        "cve",
        "zero-day",
        "zero day",
        "apt",
        "malware",
        "phishing",
        "vulnerability",
        "solarwinds",
        "crowdstrike",
        "malware",
        "exploit",
        "spyware",
        "deepfake scam",
        "cyberattack",
        "cyber attack",
    ),
    "autonomous_vehicles": (
        "robotaxi",
        "self-driving",
        "self driving",
        "autonomous vehicle",
        "autonomous truck",
        "waymo",
        "cruise",
        "tesla fsd",
        "lidar",
        "drone",
        "uav",
        "dji",
        "delivery robot",
        "av regulation",
        "fcc drone",
        "vehicle cybersecurity",
        "byd",
        "autonomous driving",
    ),
}

_OFFTOPIC_CUES: tuple[str, ...] = (
    "diplomatic appointment",
    "ambassador",
    "subscription price",
    "disney+",
    "disney plus",
    "streaming plan",
    "ad tier",
    "box office",
    "election result",
    "sports score",
    "weather forecast",
    "celebrity wedding",
    "robin williams",
)

_META_LANGUAGE = re.compile(
    r"(?i)\b("
    r"hacker\s*news|show\s*hn|posted\s+on\s+hn|hn\s+thread|hn\s+post|"
    r"according\s+to\s+(a\s+)?(hn|hacker\s*news)\b|"
    r"front\s*page\s+of\s+hacker\s*news|"
    r"reddit\s+thread|as\s+discussed\s+on\s+hn"
    r")\b"
)

_LISTICLE_OR_INDEX = re.compile(
    r"(?i)\b("
    r"top\s+\d+|best\s+\d+|\d+\s+best|wholesale\s+websites|"
    r"roundup|things\s+to\s+know|what\s+to\s+watch|"
    r"complete\s+guide|ultimate\s+guide|index\s+of|"
    r"all\s+the\s+news|latest\s+news\s+and\s+releases"
    r")\b"
)

_INDEX_PATH_HINTS = (
    "/bangladesh",
    "/category/",
    "/tag/",
    "/topics/",
    "/section/",
    "/news/",
)


def card_text_blob(card: dict[str, Any]) -> str:
    parts = [
        str(card.get("headline") or ""),
        str(card.get("blurb") or ""),
        str(card.get("why_it_matters") or ""),
        str(card.get("cluster_title") or ""),
    ]
    for s in card.get("sources") or []:
        if isinstance(s, dict):
            parts.append(str(s.get("title") or ""))
    return " ".join(parts)


def has_meta_language(text: str) -> bool:
    return bool(_META_LANGUAGE.search(text or ""))


def looks_like_listicle_or_index(title: str, url: str = "") -> bool:
    t = title or ""
    if _LISTICLE_OR_INDEX.search(t):
        return True
    path = ""
    try:
        from urllib.parse import urlparse

        path = (urlparse(url or "").path or "").lower()
    except Exception:
        path = (url or "").lower()
    # Bare section/index paths with very short titles are usually not a story.
    if any(h in path for h in _INDEX_PATH_HINTS) and len(significant_tokens(t, limit=8)) <= 2:
        return True
    # Domain homepage-ish paths.
    if path in {"", "/", "/news", "/bangladesh"} and len(t.split()) <= 4:
        return True
    return False


def low_engagement_social(source: dict[str, Any]) -> bool:
    """Drop social posts with very low engagement when used as corroboration."""
    url = (source.get("url") or "").lower()
    host = extract_domain(url)
    social = host.endswith("twitter.com") or host.endswith("x.com") or host.endswith(
        "truthsocial.com"
    )
    if not social:
        return False
    eng = source.get("engagement") if isinstance(source.get("engagement"), dict) else {}
    points = int(eng.get("points") or eng.get("likes") or eng.get("score") or 0)
    return points < 50


def category_scores(text: str) -> dict[str, float]:
    tl = (text or "").lower()
    scores = {s: 0.0 for s in TOPIC_CATEGORY_SLUGS}
    for slug, cues in _CATEGORY_CUES.items():
        for cue in cues:
            if cue in tl:
                # Longer cues are more specific.
                scores[slug] += 1.0 + min(2.0, len(cue) / 12.0)
    return scores


def offtopic_score(text: str) -> float:
    tl = (text or "").lower()
    score = 0.0
    for cue in _OFFTOPIC_CUES:
        if cue in tl:
            score += 2.0
    # Weak tech signal overall.
    cat_scores = category_scores(tl)
    if max(cat_scores.values() or [0.0]) < 1.0 and score > 0:
        score += 1.0
    return score


def suggest_category(text: str, current: str | None = None) -> str | None:
    """
    Return best topic slug, ``not_tech_news`` to drop, or None if uncertain.

    Does not invent a sixth publishable category — off-topic means drop.
    """
    scores = category_scores(text)
    best_slug = max(scores, key=scores.get)
    best = scores[best_slug]
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    off = offtopic_score(text)
    if off >= 2.0 and off >= best:
        return "not_tech_news"
    if best < 1.5:
        return None
    if best < second + 0.75 and current in TOPIC_CATEGORY_SLUGS:
        # Ambiguous — keep current assignment.
        return current
    return best_slug


_GENERIC_EVENT_TOKENS = frozenset(
    """
    hack hacked hacking security researchers researcher research expert easily
    vehicle vehicles drone drones robot robots update news report says said
    system systems using used into after over into from with this that
    """.split()
)


def same_event_pair(title_a: str, title_b: str) -> bool:
    """True when two titles appear to cover the same company/product/incident."""
    a = significant_tokens(title_a, limit=16)
    b = significant_tokens(title_b, limit=16)
    if not a or not b:
        return False
    overlap = a & b
    distinctive = {t for t in overlap if t not in _GENERIC_EVENT_TOKENS}
    if len(distinctive) >= 2:
        return True
    strong = {
        t
        for t in distinctive
        if len(t) >= 5 or any(ch.isdigit() for ch in t)
    }
    return len(strong) >= 2


def mixed_cluster_source_titles(titles: list[str]) -> bool:
    """True if sources look like unrelated stories bundled together."""
    clean = [t for t in titles if (t or "").strip()]
    if len(clean) < 3:
        return False
    # Compare each title to the first (seed); many unrelated = mixed.
    seed = clean[0]
    related = sum(1 for t in clean[1:] if same_event_pair(seed, t))
    unrelated = (len(clean) - 1) - related
    return unrelated >= 2 and unrelated > related


def source_supports_card(card: dict[str, Any], source: dict[str, Any]) -> bool:
    """Drop sources that do not share enough cues with the card headline/blurb."""
    title = str(source.get("title") or "")
    url = str(source.get("url") or "")
    if looks_like_listicle_or_index(title, url):
        return False
    if low_engagement_social(source):
        return False
    card_tokens = significant_tokens(
        " ".join(
            [
                str(card.get("headline") or ""),
                str(card.get("cluster_title") or ""),
                str(card.get("blurb") or "")[:180],
            ]
        ),
        limit=20,
    )
    src_tokens = significant_tokens(title, limit=16)
    if not card_tokens or not src_tokens:
        return False
    overlap = card_tokens & src_tokens
    if len(overlap) >= 2:
        return True
    strong = {t for t in overlap if len(t) >= 5}
    return len(strong) >= 1 and len(next(iter(strong))) >= 6


def filter_card_sources(card: dict[str, Any]) -> dict[str, Any]:
    """Keep up to MAX_SOURCES_PER_CARD supporting sources; prefer earlier (seed) ones."""
    sources = [s for s in (card.get("sources") or []) if isinstance(s, dict)]
    if not sources:
        return card
    kept: list[dict[str, Any]] = []
    for i, s in enumerate(sources):
        # Always keep the first source if present (primary).
        if i == 0 or source_supports_card(card, s):
            if looks_like_listicle_or_index(str(s.get("title") or ""), str(s.get("url") or "")):
                if i != 0:
                    continue
            kept.append(s)
        if len(kept) >= MAX_SOURCES_PER_CARD:
            break
    card = dict(card)
    card["sources"] = kept
    from .sources import independent_outlet_count

    n = independent_outlet_count(kept)
    is_paper = bool(card.get("is_research_paper"))
    if is_paper and n <= 1:
        card["single_source"] = False
    else:
        card["single_source"] = n < 2
    return card


_CLAIM_TOKEN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}|\d+(?:\.\d+)?%?|[A-Z]{2,}(?:-\d+)?)\b"
)


def unsupported_claim_tokens(card: dict[str, Any], source_text: str) -> list[str]:
    """
    Heuristic grounding: proper nouns / numbers in the blurb that never appear
    in concatenated source text.
    """
    blurb = f"{card.get('headline') or ''} {card.get('blurb') or ''} {card.get('why_it_matters') or ''}"
    src = (source_text or "").lower()
    bad: list[str] = []
    # Skip very common tech words that often appear only in the card framing.
    allow = {
        "tech",
        "news",
        "today",
        "users",
        "company",
        "companies",
        "security",
        "ai",
        "ml",
    }
    for m in _CLAIM_TOKEN.finditer(blurb):
        tok = m.group(1)
        if tok.lower() in allow or len(tok) < 3:
            continue
        # Titles like "Former" are often editorialized.
        if tok.lower() in {"former", "president", "both", "same"}:
            if tok.lower() not in src:
                bad.append(tok)
            continue
        if tok.lower() not in src and tok not in (source_text or ""):
            # Numbers must match exactly when present.
            bad.append(tok)
    # Deduplicate preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in bad:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:12]


def recheck_card_category(card: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """
    Re-check category; return ``(card_or_none, flag)``.

    ``flag`` is a short reason when the card is dropped or moved.
    """
    text = card_text_blob(card)
    current = card.get("category") or GENERAL_SLUG
    suggested = suggest_category(text, current=current if isinstance(current, str) else None)
    if suggested == "not_tech_news":
        return None, "off_topic"
    if suggested and suggested in TOPIC_CATEGORY_SLUGS and suggested != current:
        card = dict(card)
        card["category"] = suggested
        return card, f"moved:{current}->{suggested}"
    if current == GENERAL_SLUG and suggested in TOPIC_CATEGORY_SLUGS:
        card = dict(card)
        card["category"] = suggested
        return card, f"moved:general->{suggested}"
    return card, None


def audit_feed_cards(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Offline audit used by verify --fixture.

    Returns lists of flagged items keyed by problem type.
    """
    flags: dict[str, list[dict[str, Any]]] = {
        "category_mismatch": [],
        "off_topic": [],
        "mixed_cluster": [],
        "weak_corroboration": [],
        "meta_language": [],
        "too_many_sources": [],
    }
    for i, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        head = (card.get("headline") or "")[:80]
        text = card_text_blob(card)
        current = card.get("category")
        suggested = suggest_category(text, current=current if isinstance(current, str) else None)
        if suggested == "not_tech_news":
            flags["off_topic"].append({"index": i, "headline": head, "category": current})
        elif (
            suggested
            and suggested in TOPIC_CATEGORY_SLUGS
            and current in TOPIC_CATEGORY_SLUGS
            and suggested != current
        ):
            flags["category_mismatch"].append(
                {
                    "index": i,
                    "headline": head,
                    "category": current,
                    "suggested": suggested,
                }
            )

        titles = [
            str(s.get("title") or "")
            for s in (card.get("sources") or [])
            if isinstance(s, dict)
        ]
        if mixed_cluster_source_titles(titles):
            flags["mixed_cluster"].append(
                {"index": i, "headline": head, "sources": len(titles)}
            )

        sources = [s for s in (card.get("sources") or []) if isinstance(s, dict)]
        if len(sources) > MAX_SOURCES_PER_CARD:
            flags["too_many_sources"].append(
                {"index": i, "headline": head, "sources": len(sources)}
            )
        weak = []
        for s in sources[1:]:
            title = str(s.get("title") or "")
            url = str(s.get("url") or "")
            if looks_like_listicle_or_index(title, url) or not source_supports_card(card, s):
                weak.append(title[:60] or url[:60])
        if weak:
            flags["weak_corroboration"].append(
                {"index": i, "headline": head, "weak": weak[:3]}
            )

        blob = f"{card.get('blurb') or ''} {card.get('why_it_matters') or ''}"
        if has_meta_language(blob) or has_meta_language(str(card.get("headline") or "")):
            flags["meta_language"].append({"index": i, "headline": head})

    return flags


def split_mixed_clusters(
    clusters: list[dict[str, Any]], articles: list[Any]
) -> list[dict[str, Any]]:
    """
    Split clusters whose article titles do not share a common event.

    No extra LLM calls — purely index surgery.
    """
    out: list[dict[str, Any]] = []
    for cluster in clusters:
        idxs = [
            i
            for i in (cluster.get("article_indices") or [])
            if isinstance(i, int) and 0 <= i < len(articles)
        ]
        if len(idxs) <= 1:
            out.append(cluster)
            continue
        titles = []
        for i in idxs:
            a = articles[i]
            titles.append(getattr(a, "title", None) or "")
        if not mixed_cluster_source_titles(titles):
            # Still cap cluster size to avoid mega-bundles.
            if len(idxs) > MAX_SOURCES_PER_CARD:
                seed = dict(cluster)
                seed["article_indices"] = idxs[:MAX_SOURCES_PER_CARD]
                out.append(seed)
            else:
                out.append(cluster)
            continue
        # Greedy: grow groups of same-event articles.
        used: set[int] = set()
        for i in idxs:
            if i in used:
                continue
            group = [i]
            used.add(i)
            t0 = getattr(articles[i], "title", None) or ""
            for j in idxs:
                if j in used:
                    continue
                t1 = getattr(articles[j], "title", None) or ""
                if same_event_pair(t0, t1):
                    group.append(j)
                    used.add(j)
                if len(group) >= MAX_SOURCES_PER_CARD:
                    break
            piece = dict(cluster)
            piece["article_indices"] = group
            if len(group) == 1:
                piece["cluster_title"] = (
                    getattr(articles[group[0]], "title", None) or cluster.get("cluster_title")
                )
                piece["corroborated"] = False
            out.append(piece)
    return out


def polish_cards_for_publish(
    cards: list[dict[str, Any]],
    *,
    articles_by_url: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Final offline gate before persist: category recheck, source filter, meta drop,
    light grounding drop. No LLM calls.
    """
    articles_by_url = articles_by_url or {}
    out: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        # Meta language about HN/posting venue.
        blob = f"{card.get('headline') or ''} {card.get('blurb') or ''} {card.get('why_it_matters') or ''}"
        if has_meta_language(blob):
            continue
        card = filter_card_sources(card)
        if not (card.get("sources") or []):
            continue
        card2, flag = recheck_card_category(card)
        if card2 is None:
            continue
        card = card2
        # Light grounding against available source titles (and bodies if known).
        src_bits: list[str] = []
        for s in card.get("sources") or []:
            if not isinstance(s, dict):
                continue
            src_bits.append(str(s.get("title") or ""))
            u = (s.get("url") or "").strip()
            art = articles_by_url.get(u)
            if art is not None:
                src_bits.append(getattr(art, "snippet", None) or "")
                src_bits.append((getattr(art, "full_text", None) or "")[:2000])
        unsupported = unsupported_claim_tokens(card, "\n".join(src_bits))
        # Drop only when several strong claims look invented (avoid over-pruning).
        strong_bad = [t for t in unsupported if t[:1].isupper() or any(ch.isdigit() for ch in t)]
        if len(strong_bad) >= 4:
            continue
        out.append(card)
    return out
