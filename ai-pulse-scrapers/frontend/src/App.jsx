/**
 * Responsive shell: header, category tabs, card grid, expanded + share.
 */
import { useState } from "react";
import { CardExpanded } from "./components/CardExpanded.jsx";
import { CardStack } from "./components/CardStack.jsx";
import { CategoryFilter } from "./components/CategoryFilter.jsx";
import { Header } from "./components/Header.jsx";
import { LoadingScreen } from "./components/LoadingScreen.jsx";
import { useFeed } from "./hooks/useFeed.js";
import { useTheme } from "./hooks/useTheme.js";

export default function App() {
  const { theme, resolved, setTheme } = useTheme();
  const {
    cards,
    allCards,
    categories,
    feedDate,
    generatedAt,
    loading,
    introFading,
    error,
    retryLoad,
    filterByCategory,
    activeCategory,
  } = useFeed();

  const [expanded, setExpanded] = useState(null);

  const feedEmpty = !loading && allCards.length === 0 && !error;

  if (loading) {
    return <LoadingScreen fading={introFading} />;
  }

  return (
    <div className="min-h-screen bg-tb-bg font-sans text-tb-text antialiased motion-safe:animate-fade-in">
      <div className="mx-auto w-full max-w-shell px-4 pb-8 sm:px-6 lg:px-8">
        <Header
          feedDate={feedDate}
          generatedAt={generatedAt}
          theme={theme}
          resolvedTheme={resolved}
          onThemeChange={setTheme}
        />
        {allCards.length > 0 ? (
          <CategoryFilter
            categories={categories}
            activeCategory={activeCategory}
            onFilter={filterByCategory}
          />
        ) : null}

        {error && allCards.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center">
            <p className="max-w-md text-base text-tb-muted">
              {error.includes("longer than usual")
                ? "We couldn’t load today’s cards in time. Please try again."
                : error}
            </p>
            <button
              type="button"
              onClick={retryLoad}
              className="rounded-xl bg-tb-accent px-4 py-2.5 text-sm font-semibold text-tb-accent-fg transition-transform active:scale-[0.98]"
            >
              Try again
            </button>
          </div>
        ) : null}

        {!(error && allCards.length === 0) ? (
          <CardStack
            cards={cards}
            loading={false}
            onExpandCard={setExpanded}
            emptyMessage={
              feedEmpty
                ? "No cards in today’s briefing yet."
                : "No cards in this category."
            }
          />
        ) : null}
      </div>

      <CardExpanded
        card={expanded}
        open={Boolean(expanded)}
        onClose={() => setExpanded(null)}
        resolvedTheme={resolved}
      />
    </div>
  );
}
