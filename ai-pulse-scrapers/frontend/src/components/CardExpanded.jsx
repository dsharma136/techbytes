import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { FeedCard } from "./FeedCard.jsx";
import { ShareCard } from "./ShareCard.jsx";

/**
 * Bottom sheet on mobile; centered modal on md+ (max-w-2xl).
 */
export function CardExpanded({ card, open, onClose, resolvedTheme = "dark" }) {
  const captureRef = useRef(null);
  const closeBtnRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeBtnRef.current?.focus();
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !card) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-end justify-center md:items-center md:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="expanded-card-title"
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-[var(--tb-overlay)] backdrop-blur-[6px] transition-opacity duration-300 animate-fade-in"
        onClick={onClose}
      />

      <div className="animate-sheet-up relative z-10 flex max-h-[min(92dvh,900px)] w-full max-w-2xl flex-col overflow-hidden rounded-t-[1.35rem] border border-tb-border bg-tb-bg shadow-[var(--tb-shadow-card)] md:rounded-3xl md:shadow-2xl">
        <div className="flex items-center justify-between border-b border-tb-border px-4 py-3 sm:px-5">
          <h2 id="expanded-card-title" className="text-sm font-semibold text-tb-text">
            Card detail
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-tb-subtle transition-colors duration-200 hover:bg-tb-surface hover:text-tb-text"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-2 pt-3 sm:px-5">
          <div
            ref={captureRef}
            className="rounded-2xl border border-tb-border bg-tb-surface p-1"
          >
            <FeedCard card={card} variant="expanded" />
          </div>
        </div>

        <ShareCard card={card} captureRef={captureRef} resolvedTheme={resolvedTheme} />
      </div>
    </div>
  );
}
