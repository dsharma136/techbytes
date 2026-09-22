/**
 * Category slugs align with ``llm.processor`` / API cards.
 * ``CATEGORY_ORDER`` is the display order for pills that have cards.
 * Pill classes include light + dark: variants for WCAG AA contrast.
 * Retired ``dev_tools`` cards are filtered out of the feed (legacy JSON may still contain them).
 */
export const HIDDEN_CATEGORY_SLUGS = new Set(["dev_tools"]);

export const CATEGORY_PILLS = [
  {
    slug: "ai_ml",
    label: "AI/ML",
    onCard:
      "bg-violet-100 text-violet-900 ring-1 ring-inset ring-violet-300/70 dark:bg-violet-950/50 dark:text-violet-100 dark:ring-violet-500/25",
    inactive:
      "bg-violet-50 text-violet-800 ring-1 ring-inset ring-violet-200 hover:bg-violet-100 dark:bg-violet-950/40 dark:text-violet-200 dark:ring-violet-800/40 dark:hover:bg-violet-950/60",
    active:
      "bg-violet-200 text-violet-950 ring-2 ring-inset ring-violet-500/70 dark:bg-violet-600/25 dark:text-violet-100 dark:ring-violet-400/55",
  },
  {
    slug: "chips_hardware",
    label: "Chips",
    onCard:
      "bg-amber-100 text-amber-950 ring-1 ring-inset ring-amber-300/70 dark:bg-amber-950/50 dark:text-amber-100 dark:ring-amber-500/25",
    inactive:
      "bg-amber-50 text-amber-900 ring-1 ring-inset ring-amber-200 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-800/40 dark:hover:bg-amber-950/60",
    active:
      "bg-amber-200 text-amber-950 ring-2 ring-inset ring-amber-500/70 dark:bg-amber-600/25 dark:text-amber-100 dark:ring-amber-400/55",
  },
  {
    slug: "networking_cloud",
    label: "Network",
    onCard:
      "bg-sky-100 text-sky-950 ring-1 ring-inset ring-sky-300/70 dark:bg-sky-950/50 dark:text-sky-100 dark:ring-sky-500/25",
    inactive:
      "bg-sky-50 text-sky-900 ring-1 ring-inset ring-sky-200 hover:bg-sky-100 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-800/40 dark:hover:bg-sky-950/60",
    active:
      "bg-sky-200 text-sky-950 ring-2 ring-inset ring-sky-500/70 dark:bg-sky-600/25 dark:text-sky-100 dark:ring-sky-400/55",
  },
  {
    slug: "cybersecurity",
    label: "Cyber",
    onCard:
      "bg-rose-100 text-rose-950 ring-1 ring-inset ring-rose-300/70 dark:bg-rose-950/50 dark:text-rose-100 dark:ring-rose-500/25",
    inactive:
      "bg-rose-50 text-rose-900 ring-1 ring-inset ring-rose-200 hover:bg-rose-100 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-800/40 dark:hover:bg-rose-950/60",
    active:
      "bg-rose-200 text-rose-950 ring-2 ring-inset ring-rose-500/70 dark:bg-rose-600/25 dark:text-rose-100 dark:ring-rose-400/55",
  },
  {
    slug: "autonomous_vehicles",
    label: "AV",
    onCard:
      "bg-emerald-100 text-emerald-950 ring-1 ring-inset ring-emerald-300/70 dark:bg-emerald-950/50 dark:text-emerald-100 dark:ring-emerald-500/25",
    inactive:
      "bg-emerald-50 text-emerald-900 ring-1 ring-inset ring-emerald-200 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-800/40 dark:hover:bg-emerald-950/60",
    active:
      "bg-emerald-200 text-emerald-950 ring-2 ring-inset ring-emerald-500/70 dark:bg-emerald-600/25 dark:text-emerald-100 dark:ring-emerald-400/55",
  },
];

export const GENERAL_PILL = {
  slug: "general",
  label: "General",
  onCard:
    "bg-slate-200/90 text-slate-800 ring-1 ring-inset ring-slate-300/80 dark:bg-slate-700/70 dark:text-slate-100 dark:ring-slate-500/40",
  inactive:
    "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-200 dark:bg-slate-800/80 dark:text-slate-300 dark:ring-slate-600/60 dark:hover:bg-slate-800",
  active:
    "bg-slate-300 text-slate-900 ring-2 ring-inset ring-slate-500/55 dark:bg-slate-600/30 dark:text-slate-100 dark:ring-slate-400/45",
};

/** Canonical pill order (only non-empty categories are shown). */
export const CATEGORY_ORDER = [...CATEGORY_PILLS, GENERAL_PILL];

/** Lookup pill config for a card category slug (fallback: general styling). */
export function pillForSlug(slug) {
  return (
    CATEGORY_ORDER.find((p) => p.slug === slug) ?? {
      ...GENERAL_PILL,
      slug,
      label: String(slug || "general").replace(/_/g, " "),
      onCard: GENERAL_PILL.onCard,
    }
  );
}

/** Drop retired / unknown categories from a feed payload. */
export function visibleCards(cards) {
  return (cards || []).filter(
    (c) => c?.category && !HIDDEN_CATEGORY_SLUGS.has(c.category),
  );
}

/**
 * Categories present in ``cards``, in canonical order.
 */
export function categoriesPresentInFeed(cards) {
  const counts = new Map();
  for (const c of visibleCards(cards)) {
    counts.set(c.category, (counts.get(c.category) || 0) + 1);
  }
  return CATEGORY_ORDER.filter((p) => (counts.get(p.slug) || 0) > 0).map((p) => p.slug);
}
