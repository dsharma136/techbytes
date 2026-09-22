import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  categoriesPresentInFeed,
  visibleCards,
} from "../constants/categories.js";
import { stableCardId } from "../utils/cardId.js";

const INTRO_MIN_MS = 3500;
const LOAD_TIMEOUT_MS = 15000;
const INTRO_FADE_MS = 450;

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function normalizeCards(feedDate, generatedAt, rawCards) {
  const list = visibleCards(Array.isArray(rawCards) ? rawCards : []);
  return list.map((c, i) => ({
    ...c,
    id: stableCardId(feedDate, c, i),
    published_at: c.published_at || generatedAt || null,
  }));
}

function applyPayload(data, setFeedDate, setGeneratedAt, setCards, setErrors) {
  const date = data?.date ?? null;
  const generatedAt = data?.generated_at ?? null;
  setFeedDate(date);
  setGeneratedAt(generatedAt);
  setCards(normalizeCards(date, generatedAt, data?.cards));
  setErrors(Array.isArray(data?.errors) ? data.errors : []);
}

async function fetchStoredFeed() {
  const res = await fetch("/api/cards/today");
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Stored-feed only: one request on load, never triggers the pipeline.
 * Branded intro (≥3.5s) then fade into the app; 15s hard timeout.
 */
export function useFeed() {
  const [feedDate, setFeedDate] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);
  const [allCards, setAllCards] = useState([]);
  const [pipelineErrors, setPipelineErrors] = useState([]);
  const [activeCategory, setActiveCategory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [introFading, setIntroFading] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);
  const loadGen = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const categories = useMemo(
    () => categoriesPresentInFeed(allCards),
    [allCards],
  );

  useEffect(() => {
    if (categories.length === 0) {
      setActiveCategory(null);
      return;
    }
    if (!activeCategory || !categories.includes(activeCategory)) {
      setActiveCategory(categories[0]);
    }
  }, [categories, activeCategory]);

  const filterByCategory = useCallback((slug) => {
    if (slug && typeof slug === "string") {
      setActiveCategory(slug);
    }
  }, []);

  const cards = useMemo(() => {
    if (!activeCategory) return [];
    return allCards.filter((c) => c.category === activeCategory);
  }, [allCards, activeCategory]);

  const finishIntro = useCallback(async () => {
    if (!mounted.current) return;
    if (prefersReducedMotion()) {
      setIntroFading(false);
      setLoading(false);
      return;
    }
    setIntroFading(true);
    await sleep(INTRO_FADE_MS);
    if (!mounted.current) return;
    setLoading(false);
    setIntroFading(false);
  }, []);

  const runInitialLoad = useCallback(async () => {
    const gen = ++loadGen.current;
    const started = Date.now();
    setLoading(true);
    setIntroFading(false);
    setError(null);

    const fetchPromise = fetchStoredFeed()
      .then((data) => ({ ok: true, data }))
      .catch((e) => ({
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      }));

    await sleep(INTRO_MIN_MS);
    if (!mounted.current || gen !== loadGen.current) return;

    const elapsed = Date.now() - started;
    const budget = Math.max(0, LOAD_TIMEOUT_MS - elapsed);

    let result;
    try {
      result = await Promise.race([
        fetchPromise,
        sleep(budget).then(() => ({
          ok: false,
          error: "Today’s cards are taking longer than usual.",
          timeout: true,
        })),
      ]);
    } catch (e) {
      result = {
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      };
    }

    if (!mounted.current || gen !== loadGen.current) return;

    if (result.ok) {
      applyPayload(
        result.data,
        setFeedDate,
        setGeneratedAt,
        setAllCards,
        setPipelineErrors,
      );
      setError(null);
      await finishIntro();
      return;
    }

    setAllCards([]);
    setFeedDate(null);
    setGeneratedAt(null);
    setPipelineErrors([]);
    setError(result.error || "Today’s cards are taking longer than usual.");
    setIntroFading(false);
    setLoading(false);
  }, [finishIntro]);

  useEffect(() => {
    runInitialLoad();
  }, [runInitialLoad]);

  const retryLoad = useCallback(async () => {
    await runInitialLoad();
  }, [runInitialLoad]);

  return {
    cards,
    allCards,
    categories,
    activeCategory,
    feedDate,
    generatedAt,
    pipelineErrors,
    loading,
    introFading,
    error,
    retryLoad,
    filterByCategory,
  };
}
