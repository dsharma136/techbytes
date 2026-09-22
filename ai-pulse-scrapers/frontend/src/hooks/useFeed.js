import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { stableCardId } from "../utils/cardId.js";

function normalizeCards(feedDate, rawCards) {
  const list = Array.isArray(rawCards) ? rawCards : [];
  return list.map((c, i) => ({
    ...c,
    id: stableCardId(feedDate, c, i),
  }));
}

function applyPayload(data, setFeedDate, setCards, setErrors) {
  const date = data?.date ?? null;
  setFeedDate(date);
  setCards(normalizeCards(date, data?.cards));
  setErrors(Array.isArray(data?.errors) ? data.errors : []);
}

/**
 * Cached-first feed: `/api/cards/today/cached` then `/api/cards/today` in background.
 */
export function useFeed() {
  const [feedDate, setFeedDate] = useState(null);
  const [allCards, setAllCards] = useState([]);
  const [pipelineErrors, setPipelineErrors] = useState([]);
  const [activeCategory, setActiveCategory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const filterByCategory = useCallback((slug) => {
    setActiveCategory(slug && slug !== "all" ? slug : null);
  }, []);

  const cards = useMemo(() => {
    if (!activeCategory) return allCards;
    return allCards.filter((c) => c.category === activeCategory);
  }, [allCards, activeCategory]);

  const categories = useMemo(() => {
    const s = new Set(allCards.map((c) => c.category).filter(Boolean));
    return Array.from(s).sort();
  }, [allCards]);

  const runBackgroundToday = useCallback(async () => {
    if (!mounted.current) return;
    setRefreshing(true);
    setError(null);
    try {
      const res = await fetch("/api/cards/today");
      if (!mounted.current) return;
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = await res.json();
      if (!mounted.current) return;
      applyPayload(data, setFeedDate, setAllCards, setPipelineErrors);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoading(true);
      setError(null);
      try {
        const cachedRes = await fetch("/api/cards/today/cached");
        if (cancelled || !mounted.current) return;

        if (cachedRes.ok) {
          const data = await cachedRes.json();
          if (cancelled || !mounted.current) return;
          applyPayload(data, setFeedDate, setAllCards, setPipelineErrors);
          setLoading(false);
          runBackgroundToday();
          return;
        }

        const todayRes = await fetch("/api/cards/today");
        if (cancelled || !mounted.current) return;
        if (!todayRes.ok) {
          const text = await todayRes.text();
          throw new Error(text || todayRes.statusText);
        }
        const data = await todayRes.json();
        if (cancelled || !mounted.current) return;
        applyPayload(data, setFeedDate, setAllCards, setPipelineErrors);
      } catch (e) {
        if (cancelled || !mounted.current) return;
        setError(e instanceof Error ? e.message : String(e));
        setAllCards([]);
        setFeedDate(null);
        setPipelineErrors([]);
      } finally {
        if (!cancelled && mounted.current) setLoading(false);
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, [runBackgroundToday]);

  const refresh = useCallback(async () => {
    setError(null);
    setRefreshing(true);
    try {
      const res = await fetch("/api/cards/today");
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
      }
      const data = await res.json();
      applyPayload(data, setFeedDate, setAllCards, setPipelineErrors);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }, []);

  return {
    cards,
    allCards,
    categories,
    activeCategory,
    feedDate,
    pipelineErrors,
    loading,
    refreshing,
    error,
    refresh,
    filterByCategory,
  };
}
