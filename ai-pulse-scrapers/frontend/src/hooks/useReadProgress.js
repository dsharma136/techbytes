import { useCallback, useEffect, useMemo, useState } from "react";

const storageKey = (feedDate) =>
  feedDate ? `ai-pulse-read:${feedDate}` : null;

function loadIds(feedDate) {
  const key = storageKey(feedDate);
  if (!key) return new Set();
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr.map(String) : []);
  } catch {
    return new Set();
  }
}

/**
 * Persists card ids the user has scrolled past for the current feed date.
 */
export function useReadProgress(feedDate, cardIds) {
  const [readSet, setReadSet] = useState(() => loadIds(feedDate));

  useEffect(() => {
    setReadSet(loadIds(feedDate));
  }, [feedDate]);

  const persist = useCallback(
    (next) => {
      const key = storageKey(feedDate);
      if (!key) return;
      localStorage.setItem(key, JSON.stringify([...next]));
    },
    [feedDate],
  );

  const markRead = useCallback(
    (id) => {
      const sid = String(id);
      setReadSet((prev) => {
        if (prev.has(sid)) return prev;
        const next = new Set(prev);
        next.add(sid);
        persist(next);
        return next;
      });
    },
    [persist],
  );

  const resetProgress = useCallback(() => {
    setReadSet(new Set());
    const key = storageKey(feedDate);
    if (key) localStorage.removeItem(key);
  }, [feedDate]);

  const totalCards = cardIds.length;
  const cardsRead = useMemo(
    () => cardIds.filter((id) => readSet.has(String(id))).length,
    [cardIds, readSet],
  );

  return {
    cardsRead,
    totalCards,
    markRead,
    resetProgress,
  };
}
