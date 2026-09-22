import { useCallback, useState } from "react";
import { Copy, ImageDown, Check } from "lucide-react";
import { formatCardPlainText } from "../utils/formatCardText.js";

/**
 * Copy full card as text; export the capture region as PNG (html2canvas).
 */
export function ShareCard({ card, captureRef }) {
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
        backgroundColor: "#0a0a0a",
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
      a.download = `ai-pulse-card-${String(card.id ?? "share").slice(0, 24)}.png`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setImgError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setImgBusy(false);
    }
  }, [captureRef, card.id]);

  return (
    <div className="flex flex-col gap-2 border-t border-neutral-800/80 bg-neutral-950/95 p-4">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={copyText}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-neutral-800/90 py-3 text-sm font-medium text-neutral-100 ring-1 ring-neutral-700/50 transition-all duration-200 hover:bg-neutral-800 hover:ring-neutral-600 active:scale-[0.98]"
        >
          {copied ? (
            <Check className="h-4 w-4 text-emerald-400" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
          {copied ? "Copied" : "Copy text"}
        </button>
        <button
          type="button"
          onClick={exportImage}
          disabled={imgBusy}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600/90 to-violet-600/85 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-950/40 transition-all duration-200 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 active:scale-[0.98]"
        >
          <ImageDown className="h-4 w-4" />
          {imgBusy ? "Saving…" : "Save image"}
        </button>
      </div>
      {imgError ? (
        <p className="text-center text-[11px] text-red-400/90">{imgError}</p>
      ) : null}
    </div>
  );
}
