import { useEffect, useRef } from "react";
import { FeedCard } from "./FeedCard.jsx";

function CardSkeleton() {
  return (
    <div
      className="animate-pulse rounded-2xl border border-neutral-800/80 bg-neutral-900/40 p-4 ring-1 ring-white/[0.03]"
      aria-hidden
    >
      <div className="mb-3 flex justify-between gap-2">
        <div className="h-6 w-20 rounded-lg bg-neutral-800/80" />
        <div className="h-6 w-16 rounded-full bg-neutral-800/60" />
      </div>
      <div className="space-y-2">
        <div className="h-4 w-full rounded bg-neutral-800/70" />
        <div className="h-4 w-[92%] rounded bg-neutral-800/50" />
        <div className="h-4 w-[70%] rounded bg-neutral-800/50" />
      </div>
      <div className="mt-5 space-y-2 border-t border-neutral-800/60 pt-4">
        <div className="h-2 w-24 rounded bg-neutral-800/50" />
        <div className="h-3 w-full rounded bg-neutral-800/40" />
        <div className="h-3 w-[88%] rounded bg-neutral-800/35" />
      </div>
      <div className="mt-4 h-8 w-full rounded-lg bg-neutral-800/30" />
    </div>
  );
}

/**
 * Vertical scroll, read tracking, optional skeletons while loading.
 */
export function CardStack({
  cards,
  loading,
  onCardPastViewport,
  onExpandCard,
  emptyMessage,
  skeletonCount = 5,
}) {
  const scrollRef = useRef(null);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root || cards.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) continue;
          const el = entry.target;
          const id = el.dataset.cardId;
          if (!id) continue;
          const rootRect = root.getBoundingClientRect();
          const cardRect = el.getBoundingClientRect();
          if (cardRect.bottom < rootRect.top) {
            onCardPastViewport(id);
          }
        }
      },
      { root, rootMargin: "0px", threshold: 0 },
    );

    for (const el of root.querySelectorAll("[data-card-id]")) {
      observer.observe(el);
    }

    return () => observer.disconnect();
  }, [cards, onCardPastViewport]);

  const showSkeleton = loading && cards.length === 0;

  if (showSkeleton) {
    return (
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-8 pt-2"
      >
        <div className="mx-auto flex w-full max-w-[375px] flex-col gap-4">
          {Array.from({ length: skeletonCount }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-16 text-center text-sm text-neutral-500">
        {emptyMessage ?? "No cards to show."}
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-8 pt-2"
    >
      <div className="mx-auto flex w-full max-w-[375px] flex-col gap-5">
        {cards.map((card) => (
          <article
            key={card.id}
            data-card-id={card.id}
            className="scroll-mt-3 animate-card-in"
          >
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
