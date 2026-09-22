/**
 * Engagement badge from clustering importance + optional HN signals (project article schema).
 */

function maxHnEngagement(sources) {
  if (!Array.isArray(sources)) return 0;
  let max = 0;
  for (const s of sources) {
    const e = s?.engagement;
    if (!e || typeof e !== "object") continue;
    const pts = Number(e.points) || 0;
    if (pts > max) max = pts;
  }
  return max;
}

/**
 * @returns {{ label: string, className: string } | null}
 */
export function engagementBadge(card) {
  const score =
    typeof card.importance_score === "number" && !Number.isNaN(card.importance_score)
      ? card.importance_score
      : null;
  const hn = maxHnEngagement(card.sources);

  if (score != null && score >= 0.82) {
    return {
      label: "Hot story",
      className:
        "bg-gradient-to-r from-orange-600/90 via-rose-500/85 to-amber-500/80 text-white shadow-[0_0_16px_-2px_rgba(251,146,60,0.5)]",
    };
  }
  if (score != null && score >= 0.62) {
    return {
      label: "Rising",
      className:
        "bg-gradient-to-r from-violet-600/80 to-fuchsia-600/75 text-white shadow-[0_0_14px_-2px_rgba(168,85,247,0.45)]",
    };
  }
  if (hn >= 400) {
    return {
      label: `HN ${hn >= 1000 ? `${Math.round(hn / 100) / 10}k` : hn} pts`,
      className:
        "bg-gradient-to-r from-amber-700/85 to-orange-600/80 text-amber-50 ring-1 ring-amber-400/30",
    };
  }
  if (score != null) {
    return {
      label: "Spotlight",
      className:
        "bg-neutral-800/90 text-neutral-200 ring-1 ring-neutral-600/50",
    };
  }
  return null;
}
