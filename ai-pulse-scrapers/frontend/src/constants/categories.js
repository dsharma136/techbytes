/**
 * Category slugs align with ``llm.processor`` / API cards.
 * Pill styles: inactive (muted) vs active (tinted + ring).
 */
export const CATEGORY_PILLS = [
  {
    slug: "ai_ml",
    label: "AI/ML",
    onCard:
      "bg-violet-950/50 text-violet-100/95 ring-1 ring-violet-500/25 shadow-[0_0_20px_-8px_rgba(139,92,246,0.35)]",
    inactive:
      "bg-violet-950/40 text-violet-200/80 ring-1 ring-violet-800/40 hover:bg-violet-950/60",
    active: "bg-violet-600/25 text-violet-100 ring-2 ring-violet-400/50 shadow-[0_0_20px_-4px_rgba(139,92,246,0.45)]",
  },
  {
    slug: "chips_hardware",
    label: "Chips",
    onCard:
      "bg-amber-950/50 text-amber-100/95 ring-1 ring-amber-500/25 shadow-[0_0_20px_-8px_rgba(245,158,11,0.25)]",
    inactive:
      "bg-amber-950/40 text-amber-200/80 ring-1 ring-amber-800/40 hover:bg-amber-950/60",
    active: "bg-amber-600/25 text-amber-100 ring-2 ring-amber-400/50 shadow-[0_0_20px_-4px_rgba(245,158,11,0.35)]",
  },
  {
    slug: "networking_cloud",
    label: "Network",
    onCard:
      "bg-sky-950/50 text-sky-100/95 ring-1 ring-sky-500/25 shadow-[0_0_20px_-8px_rgba(14,165,233,0.22)]",
    inactive:
      "bg-sky-950/40 text-sky-200/80 ring-1 ring-sky-800/40 hover:bg-sky-950/60",
    active: "bg-sky-600/25 text-sky-100 ring-2 ring-sky-400/50 shadow-[0_0_20px_-4px_rgba(14,165,233,0.35)]",
  },
  {
    slug: "cybersecurity",
    label: "Cyber",
    onCard:
      "bg-rose-950/50 text-rose-100/95 ring-1 ring-rose-500/25 shadow-[0_0_20px_-8px_rgba(244,63,94,0.22)]",
    inactive:
      "bg-rose-950/40 text-rose-200/80 ring-1 ring-rose-800/40 hover:bg-rose-950/60",
    active: "bg-rose-600/25 text-rose-100 ring-2 ring-rose-400/50 shadow-[0_0_20px_-4px_rgba(244,63,94,0.35)]",
  },
  {
    slug: "autonomous_vehicles",
    label: "AV",
    onCard:
      "bg-emerald-950/50 text-emerald-100/95 ring-1 ring-emerald-500/25 shadow-[0_0_20px_-8px_rgba(16,185,129,0.22)]",
    inactive:
      "bg-emerald-950/40 text-emerald-200/80 ring-1 ring-emerald-800/40 hover:bg-emerald-950/60",
    active: "bg-emerald-600/25 text-emerald-100 ring-2 ring-emerald-400/50 shadow-[0_0_20px_-4px_rgba(16,185,129,0.35)]",
  },
  {
    slug: "dev_tools",
    label: "Dev",
    onCard:
      "bg-cyan-950/50 text-cyan-100/95 ring-1 ring-cyan-500/25 shadow-[0_0_20px_-8px_rgba(6,182,212,0.22)]",
    inactive:
      "bg-cyan-950/40 text-cyan-200/80 ring-1 ring-cyan-800/40 hover:bg-cyan-950/60",
    active: "bg-cyan-600/25 text-cyan-100 ring-2 ring-cyan-400/50 shadow-[0_0_20px_-4px_rgba(6,182,212,0.35)]",
  },
];

export const GENERAL_PILL = {
  slug: "general",
  label: "General",
  onCard:
    "bg-neutral-800/70 text-neutral-200/95 ring-1 ring-neutral-600/40",
  inactive:
    "bg-neutral-800/80 text-neutral-300 ring-1 ring-neutral-700/60 hover:bg-neutral-800",
  active: "bg-neutral-600/30 text-neutral-100 ring-2 ring-neutral-400/40",
};

/** Lookup pill config for a card category slug (fallback: general styling). */
export function pillForSlug(slug) {
  const base =
    CATEGORY_PILLS.find((p) => p.slug === slug) ?? {
      ...GENERAL_PILL,
      slug,
      label: String(slug || "general").replace(/_/g, " "),
      onCard: GENERAL_PILL.onCard,
    };
  return base;
}
