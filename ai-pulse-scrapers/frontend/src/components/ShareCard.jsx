import { useCallback, useState } from "react";
import { Copy, ImageDown, Check } from "lucide-react";
import { formatCardPlainText } from "../utils/formatCardText.js";

/**
 * Copy full card as text; export the capture region as PNG (html2canvas).
 */
export function ShareCard({ card, captureRef, resolvedTheme = "dark" }) {
  const [copied, setCopied] = useState(false);
  const [imgBusy, setImgBusy] = useState(false);
  const [imgError, setImgError] = useState(null);

  const copyText = useCallback(async () => {
    const text = formatCardPlainText(card);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [card]);

  const exportImage = useCallback(async () => {
    const el = captureRef?.current;
    if (!el) return;
    setImgError(null);
    setImgBusy(true);
    try {
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(el, {
        scale: 2,
        backgroundColor: resolvedTheme === "light" ? "#ffffff" : "#1e293b",
        logging: false,
        useCORS: true,
      });
      const blob = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/png", 0.95),
      );
      if (!blob) throw new Error("Could not create image");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `techbytes-card-${String(card.id ?? "share").slice(0, 24)}.png`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setImgError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setImgBusy(false);
    }
  }, [captureRef, card.id, resolvedTheme]);

  return (
    <div className="flex flex-col gap-2 border-t border-tb-border bg-tb-surface-2/80 p-4 sm:px-5">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={copyText}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-tb-border bg-tb-surface py-3 text-sm font-medium text-tb-text transition-all duration-200 hover:border-tb-border-strong hover:bg-tb-bg active:scale-[0.98]"
        >
          {copied ? (
            <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
          {copied ? "Copied" : "Copy text"}
        </button>
        <button
          type="button"
          onClick={exportImage}
          disabled={imgBusy}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-slate-800 py-3 text-sm font-semibold text-slate-50 shadow-sm transition-all duration-200 hover:bg-slate-700 disabled:opacity-50 active:scale-[0.98] dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
        >
          <ImageDown className="h-4 w-4" />
          {imgBusy ? "Saving…" : "Save image"}
        </button>
      </div>
      {imgError ? (
        <p className="text-center text-[11px] text-red-600 dark:text-red-400/90">{imgError}</p>
      ) : null}
    </div>
  );
}
