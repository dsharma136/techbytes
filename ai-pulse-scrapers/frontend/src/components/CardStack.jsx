import { FeedCard } from "./FeedCard.jsx";

function CardSkeleton() {
  return (
    <div
      className="animate-pulse rounded-2xl border border-tb-border bg-tb-surface p-4"
      aria-hidden
    >
      <div className="mb-3 flex justify-between gap-2">
        <div className="h-6 w-20 rounded-lg bg-tb-surface-2 dark:bg-slate-700/80" />
        <div className="h-6 w-16 rounded-full bg-tb-surface-2 dark:bg-slate-700/60" />
      </div>
      <div className="space-y-2">
        <div className="h-4 w-full rounded bg-tb-surface-2 dark:bg-slate-700/70" />
        <div className="h-4 w-[92%] rounded bg-tb-surface-2 dark:bg-slate-700/50" />
        <div className="h-4 w-[70%] rounded bg-tb-surface-2 dark:bg-slate-700/50" />
      </div>
      <div className="mt-5 space-y-2 border-t border-tb-border pt-4">
        <div className="h-2 w-24 rounded bg-tb-surface-2 dark:bg-slate-700/50" />
        <div className="h-3 w-full rounded bg-tb-surface-2 dark:bg-slate-700/40" />
        <div className="h-3 w-[88%] rounded bg-tb-surface-2 dark:bg-slate-700/35" />
      </div>
    </div>
  );
}

/**
 * Responsive grid: 1 col phone, 2 md, 3 lg.
 * Cards size to their content (no equal-height stretch / clipping).
 */
export function CardStack({
  cards,
  loading,
  onExpandCard,
  emptyMessage,
  skeletonCount = 6,
}) {
  const showSkeleton = loading && cards.length === 0;

  if (showSkeleton) {
    return (
      <div className="pb-10 pt-3">
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 md:gap-5 lg:grid-cols-3">
          {Array.from({ length: skeletonCount }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="flex items-center justify-center px-6 py-16 text-center text-sm text-tb-subtle">
        {emptyMessage ?? "No cards to show."}
      </div>
    );
  }

  return (
    <div className="pb-12 pt-3">
      <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 md:gap-5 lg:grid-cols-3">
        {cards.map((card) => (
          <article key={card.id} className="min-w-0 animate-card-in">
            <FeedCard
              card={card}
              onOpen={onExpandCard ? () => onExpandCard(card) : undefined}
            />
          </article>
        ))}
      </div>
    </div>
  );
}
