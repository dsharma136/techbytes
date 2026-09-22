/**
 * Gradient read progress + numeric label (e.g. 12 of 50).
 */
export function ProgressBar({ cardsRead, totalCards }) {
  const pct =
    totalCards > 0 ? Math.min(100, Math.round((cardsRead / totalCards) * 100)) : 0;

  return (
    <div
      className="px-4 pb-3 pt-0"
      aria-label={`Read progress: ${cardsRead} of ${totalCards} cards`}
    >
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-neutral-800/90 ring-1 ring-neutral-700/40">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-cyan-400 to-violet-500 transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent)",
            backgroundSize: "200% 100%",
            animation: "shimmer 2.2s ease-in-out infinite",
          }}
        />
      </div>
      <p className="mt-2 text-center text-xs font-medium tabular-nums tracking-tight text-neutral-400">
        {totalCards === 0 ? (
          <span className="text-neutral-500">No cards yet</span>
        ) : (
          <>
            <span className="text-neutral-200">{cardsRead}</span>
            <span className="text-neutral-600"> of </span>
            <span className="text-neutral-300">{totalCards}</span>
          </>
        )}
      </p>
    </div>
  );
}
