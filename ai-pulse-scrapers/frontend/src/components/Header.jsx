import { RefreshCw } from "lucide-react";

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
 * Title, feed date (UTC), refresh.
 */
export function Header({ feedDate, onRefresh, refreshing, loading }) {
  const busy = refreshing || loading;

  return (
    <header className="flex items-center justify-between gap-3 px-4 py-3.5">
      <div className="min-w-0">
        <h1 className="text-[1.35rem] font-bold tracking-tight text-neutral-50">
          AI Pulse
        </h1>
        <p className="mt-0.5 text-xs font-medium text-neutral-500">
          {formatFeedDate(feedDate)}
        </p>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        disabled={busy}
        aria-busy={busy}
        className="flex shrink-0 items-center gap-2 rounded-xl border border-neutral-700/80 bg-neutral-900/90 px-3.5 py-2 text-xs font-semibold text-neutral-100 shadow-sm transition-all duration-200 hover:border-neutral-600 hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-45 active:scale-[0.97]"
      >
        <RefreshCw
          className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`}
          aria-hidden
        />
        {busy ? "Updating" : "Refresh"}
      </button>
    </header>
  );
}
