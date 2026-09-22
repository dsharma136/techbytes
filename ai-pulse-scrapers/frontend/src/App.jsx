/**
 * Mobile-first shell (375px): header, progress, filters, card stack, expanded + share.
 */
import { useMemo, useState } from "react";
import { CardExpanded } from "./components/CardExpanded.jsx";
import { CardStack } from "./components/CardStack.jsx";
import { CategoryFilter } from "./components/CategoryFilter.jsx";
import { Header } from "./components/Header.jsx";
import { ProgressBar } from "./components/ProgressBar.jsx";
import { useFeed } from "./hooks/useFeed.js";
import { useReadProgress } from "./hooks/useReadProgress.js";

export default function App() {
  const {
    cards,
    allCards,
    feedDate,
    loading,
    refreshing,
    error,
    refresh,
    filterByCategory,
    activeCategory,
  } = useFeed();

  const [expanded, setExpanded] = useState(null);

  const cardIds = useMemo(() => cards.map((c) => c.id), [cards]);
  const { cardsRead, totalCards, markRead, resetProgress } = useReadProgress(
    feedDate,
    cardIds,
  );

  return (
    <div className="min-h-screen bg-neutral-950 font-sans text-neutral-100 antialiased">
      <div className="mx-auto flex h-[100dvh] max-h-[100dvh] min-h-0 w-full max-w-[375px] flex-col border-x border-neutral-900/90 shadow-[0_0_80px_-20px_rgba(0,0,0,0.9)]">
        <Header
          feedDate={feedDate}
          onRefresh={refresh}
          refreshing={refreshing}
          loading={loading}
        />
        <ProgressBar cardsRead={cardsRead} totalCards={totalCards} />
        <CategoryFilter
          activeCategory={activeCategory}
          onFilter={filterByCategory}
        />

        {error && cards.length === 0 && !loading ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-12 text-center">
            <p className="text-sm text-red-400/90">{error}</p>
            <button
              type="button"
              onClick={refresh}
              className="rounded-xl bg-neutral-100 px-4 py-2.5 text-sm font-semibold text-neutral-950 transition-transform active:scale-[0.98]"
            >
              Try again
            </button>
          </div>
        ) : null}

        {!(error && cards.length === 0 && !loading) ? (
          <>
            {error && cards.length > 0 ? (
              <p className="px-4 py-2 text-center text-[11px] leading-snug text-amber-500/95">
                Background update failed — showing cached cards. ({error})
              </p>
            ) : null}
            <div className="flex min-h-0 flex-1 flex-col">
              <CardStack
                cards={cards}
                loading={loading}
                onCardPastViewport={markRead}
                onExpandCard={setExpanded}
                emptyMessage={
                  allCards.length === 0
                    ? "No cards in today’s briefing yet."
                    : "No cards match this filter."
                }
              />
            </div>
            <footer className="border-t border-neutral-900/90 px-4 py-3 text-center">
              <button
                type="button"
                onClick={resetProgress}
                className="text-[11px] font-medium text-neutral-500 underline-offset-2 transition-colors hover:text-neutral-400 hover:underline"
              >
                Reset read progress
              </button>
            </footer>
          </>
        ) : null}
      </div>

      <CardExpanded
        card={expanded}
        open={Boolean(expanded)}
        onClose={() => setExpanded(null)}
      />
    </div>
  );
}
