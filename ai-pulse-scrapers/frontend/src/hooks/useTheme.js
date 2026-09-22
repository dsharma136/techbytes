import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "techbytes-theme";
const MODES = new Set(["light", "dark"]);

function readStoredTheme() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    // Migrate legacy "system" preference to dark (site default).
    if (raw === "system") return "dark";
    if (MODES.has(raw)) return raw;
  } catch {
    /* ignore */
  }
  return "dark";
}

function applyDomTheme(resolved) {
  const root = document.documentElement;
  if (resolved === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
}

/**
 * Theme mode: light | dark. Default is dark for every visitor.
 * Persists the visitor's choice in localStorage.
 */
export function useTheme() {
  const [theme, setThemeState] = useState(readStoredTheme);

  useEffect(() => {
    applyDomTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next) => {
    const mode = next === "light" ? "light" : "dark";
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      /* ignore */
    }
    setThemeState(mode);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [setTheme, theme]);

  return { theme, resolved: theme, setTheme, toggleTheme };
}
