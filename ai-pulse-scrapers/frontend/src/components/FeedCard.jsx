import { forwardRef } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";
import { pillForSlug } from "../constants/categories.js";
import { engagementBadge } from "../utils/engagement.js";

function sourceIcon(sourceType) {
  switch (sourceType) {
    case "hackernews":
      return "HN";
    case "arxiv":
      return "arXiv";
    case "brave":
      return "Web";
    default:
      return "•";
  }
}

/**
 * Micro-learning unit: headline, blurb, WHY IT MATTERS, sources, engagement.
 * Matches API card shape (``FeedCard`` / Groq writer + pipeline ``sources``).
 */
export const FeedCard = forwardRef(function FeedCard(
  { card, onOpen, variant = "stack", className = "" },
  ref,
) {
  const pill = pillForSlug(card.category);
  const badge = engagementBadge(card);
  const sources = Array.isArray(card.sources) ? card.sources : [];
  const isExpanded = variant === "expanded";
  const displayedSources = isExpanded ? sources : sources.slice(0, 3);
  const more = isExpanded ? 0 : Math.max(0, sources.length - displayedSources.length);
  const categoryClass = pill.onCard ?? pill.inactive;
  const pad = isExpanded ? "p-5" : "p-4";

  return (
    <div
      ref={ref}
      className={[
        "group relative overflow-hidden rounded-2xl transition-[transform,box-shadow] duration-300 ease-out",
        "bg-gradient-to-br from-neutral-900/95 via-neutral-950 to-neutral-950",
        "ring-1 ring-white/[0.06] shadow-[0_20px_50px_-24px_rgba(0,0,0,0.9)]",
        "hover:ring-white/[0.10] hover:shadow-[0_24px_60px_-20px_rgba(0,0,0,0.85)]",
        onOpen ? "cursor-pointer active:scale-[0.99]" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen}
      onKeyDown={
        onOpen
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,0.12), transparent 55%), radial-gradient(ellipse 60% 40% at 100% 100%, rgba(16,185,129,0.06), transparent 50%)",
        }}
      />

      <div className={`relative ${pad}`}>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <span
            className={`inline-flex items-center rounded-lg px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors duration-200 ${categoryClass}`}
          >
            {pill.label}
          </span>
          <div className="flex items-center gap-2">
            {card.is_research_paper ? (
              <span className="rounded-lg bg-violet-950/90 px-2 py-0.5 text-[10px] font-medium text-violet-200 ring-1 ring-violet-500/25">
                Paper
              </span>
            ) : null}
            {badge ? (
              <span
                className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold tracking-tight ${badge.className}`}
              >
                {badge.label}
              </span>
            ) : null}
          </div>
        </div>

        <h2
          className={`font-semibold leading-snug tracking-tight text-neutral-50 transition-colors duration-200 group-hover:text-white ${
            isExpanded ? "text-xl" : "text-[17px]"
          }`}
        >
          {card.headline}
        </h2>

        <p
          className={`mt-3 leading-relaxed text-neutral-300/95 ${
            isExpanded ? "text-[15px]" : "text-sm"
          }`}
        >
          {card.blurb}
        </p>

        <div className="mt-5 border-t border-white/[0.06] pt-4">
          <p className="text-[10px] font-bold tracking-[0.22em] text-neutral-500">
            WHY IT MATTERS
          </p>
          <p
            className={`mt-2 leading-relaxed text-neutral-400 ${
              isExpanded ? "text-[15px]" : "text-sm"
            }`}
          >
            {card.why_it_matters}
          </p>
        </div>

        {sources.length > 0 ? (
          <div className="mt-5 border-t border-white/[0.05] pt-4">
            <p className="text-[10px] font-bold tracking-[0.2em] text-neutral-500">
              SOURCES
            </p>
            <ul className="mt-2 space-y-2">
              {displayedSources.map((s, i) => (
                <li key={`${s.url}-${i}`} className="flex gap-2 text-sm">
                  <span className="shrink-0 rounded bg-neutral-800/90 px-1.5 py-0.5 text-[10px] font-medium text-neutral-400">
                    {sourceIcon(s.source_type)}
                  </span>
                  <div className="min-w-0 flex-1">
                    {isExpanded && s.url ? (
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-start gap-1 text-neutral-200 underline-offset-2 hover:text-white hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span className="line-clamp-2">{s.title}</span>
                        <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-50" />
                      </a>
                    ) : (
                      <span className="line-clamp-2 text-neutral-400">{s.title}</span>
                    )}
                    {s.source_name ? (
                      <p className="text-[11px] text-neutral-600">{s.source_name}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
            {more > 0 && !isExpanded ? (
              <p className="mt-2 text-[11px] text-neutral-500">+{more} more in expanded view</p>
            ) : null}
          </div>
        ) : (
          <p className="mt-4 text-center text-[11px] text-neutral-600">
            Curated from today&apos;s tech clusters
          </p>
        )}

        {onOpen && !isExpanded ? (
          <div className="mt-4 flex items-center justify-center gap-1 text-[11px] font-medium text-neutral-500 transition-colors duration-200 group-hover:text-neutral-400">
            Open
            <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
          </div>
        ) : null}
      </div>
    </div>
  );
});

FeedCard.displayName = "FeedCard";
