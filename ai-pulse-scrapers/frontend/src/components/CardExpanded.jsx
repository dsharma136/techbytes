import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { FeedCard } from "./FeedCard.jsx";
import { ShareCard } from "./ShareCard.jsx";

/**
 * Full-screen sheet / modal: card, all source links, share actions.
 */
export function CardExpanded({ card, open, onClose }) {
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
      className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="expanded-card-title"
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-black/75 backdrop-blur-[6px] transition-opacity duration-300 animate-fade-in"
        onClick={onClose}
      />

      <div className="animate-sheet-up relative z-10 flex max-h-[min(92dvh,820px)] w-full max-w-[375px] flex-col overflow-hidden rounded-t-[1.35rem] border border-neutral-800/90 bg-neutral-950 shadow-[0_-8px_40px_rgba(0,0,0,0.5)] sm:rounded-3xl sm:shadow-2xl">
        <div className="flex items-center justify-between border-b border-neutral-800/80 px-4 py-3">
          <h2 id="expanded-card-title" className="text-sm font-semibold text-neutral-200">
            Card detail
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-neutral-400 transition-colors duration-200 hover:bg-neutral-800 hover:text-neutral-100"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-2 pt-3">
          <div
            ref={captureRef}
            className="rounded-2xl border border-white/[0.04] bg-neutral-950 p-1"
          >
            <FeedCard card={card} variant="expanded" />
          </div>
        </div>

        <ShareCard card={card} captureRef={captureRef} />
      </div>
    </div>
  );
}
