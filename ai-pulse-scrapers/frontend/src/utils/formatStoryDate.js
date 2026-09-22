/**
 * Format a story publish time for the card chrome (viewer local timezone).
 * Under 24h: relative ("3h ago" / "12m ago"). Otherwise short date ("Sep 20").
 */
export function formatStoryDate(iso) {
  if (!iso || typeof iso !== "string") return null;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return null;

  const diffMs = Date.now() - dt.getTime();
  if (diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000) {
    const hours = Math.floor(diffMs / (60 * 60 * 1000));
    if (hours < 1) {
      const mins = Math.max(1, Math.floor(diffMs / (60 * 1000)));
      return `${mins}m ago`;
    }
    return `${hours}h ago`;
  }

  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
