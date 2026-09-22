import { Moon, Sun } from "lucide-react";

function formatFeedDate(iso) {
  if (!iso || typeof iso !== "string") return "—";
  const parts = iso.split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso;
  const [y, m, d] = parts;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(dt);
}

/**
 * Local-time label for feed generation, e.g. "Updated today at 5:04 AM".
 */
export function formatUpdatedAt(generatedAt) {
  if (!generatedAt) return null;
  const dt = new Date(generatedAt);
  if (Number.isNaN(dt.getTime())) return null;

  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(dt);

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfThatDay = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  const dayMs = 24 * 60 * 60 * 1000;
  const dayDiff = Math.round((startOfToday - startOfThatDay) / dayMs);

  if (dayDiff === 0) return `Updated today at ${time}`;
  if (dayDiff === 1) return `Updated yesterday at ${time}`;

  const date = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(dt);
  return `Updated ${date} at ${time}`;
}

/**
 * Title, feed date (UTC calendar), theme toggle, last-updated line.
 */
export function Header({
  feedDate,
  generatedAt,
  theme = "dark",
  resolvedTheme = "dark",
  onThemeChange,
}) {
  const updatedLabel = formatUpdatedAt(generatedAt);

  return (
    <header className="flex items-center justify-between gap-3 border-b border-tb-border py-3.5 sm:py-4">
      <div className="min-w-0">
        <h1 className="text-xl font-bold tracking-tight text-tb-text sm:text-[1.35rem]">
          TechBytes
        </h1>
        <p className="mt-0.5 text-xs font-medium text-tb-subtle sm:text-sm">
          {formatFeedDate(feedDate)}
        </p>
        {updatedLabel ? (
          <p className="mt-0.5 text-[11px] text-tb-subtle/90 sm:text-xs">{updatedLabel}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {typeof onThemeChange === "function" ? (
          <button
            type="button"
            onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-tb-border bg-tb-surface text-tb-muted shadow-sm transition-all duration-200 hover:border-tb-border-strong hover:bg-tb-surface-2 hover:text-tb-text active:scale-[0.97]"
          >
            {resolvedTheme === "dark" ? (
              <Sun className="h-4 w-4" aria-hidden />
            ) : (
              <Moon className="h-4 w-4" aria-hidden />
            )}
          </button>
        ) : null}
      </div>
    </header>
  );
}
