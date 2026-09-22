import { forwardRef } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";
import { pillForSlug } from "../constants/categories.js";
import { formatStoryDate } from "../utils/formatStoryDate.js";

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
 * Micro-learning unit: headline, blurb, WHY IT MATTERS, sources, publish date.
 */
export const FeedCard = forwardRef(function FeedCard(
  { card, onOpen, variant = "stack", className = "" },
  ref,
) {
  const pill = pillForSlug(card.category);
  const sources = Array.isArray(card.sources) ? card.sources : [];
  const isExpanded = variant === "expanded";
  const displayedSources = isExpanded ? sources : sources.slice(0, 3);
  const more = isExpanded ? 0 : Math.max(0, sources.length - displayedSources.length);
  const categoryClass = pill.onCard ?? pill.inactive;
  const pad = isExpanded ? "p-5 sm:p-6" : "p-4 sm:p-5";
  const dateLabel = formatStoryDate(card.published_at);

  return (
    <div
      ref={ref}
      className={[
        "group relative rounded-2xl transition-[transform,box-shadow,border-color] duration-300 ease-out",
        "border border-tb-border bg-tb-surface shadow-[var(--tb-shadow-card)]",
        "hover:border-tb-border-strong",
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
      <div className={`relative ${pad}`}>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-lg px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors duration-200 ${categoryClass}`}
            >
              {pill.label}
            </span>
            {card.is_research_paper ? (
              <span className="rounded-lg bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-900 ring-1 ring-violet-300/60 dark:bg-violet-950/90 dark:text-violet-200 dark:ring-violet-500/25">
                Paper
              </span>
            ) : null}
          </div>
          {dateLabel ? (
            <time
              dateTime={card.published_at || undefined}
              className="shrink-0 text-[11px] font-medium tabular-nums text-tb-subtle"
            >
              {dateLabel}
            </time>
          ) : null}
        </div>

        <h2
          className={`font-semibold leading-snug tracking-tight text-tb-text ${
            isExpanded ? "text-xl sm:text-[1.35rem]" : "text-[17px] sm:text-lg"
          }`}
        >
          {card.headline}
        </h2>

        <p className="mt-3 max-w-prose text-[16px] leading-[1.65] text-tb-muted sm:text-[16.5px]">
          {card.blurb}
        </p>

        <div className="mt-5 border-t border-tb-border pt-4">
          <p className="text-[10px] font-bold tracking-[0.22em] text-tb-subtle">
            WHY IT MATTERS
          </p>
          <p className="mt-2 max-w-prose text-[15px] leading-[1.65] text-tb-muted sm:text-base">
            {card.why_it_matters}
          </p>
        </div>

        {sources.length > 0 ? (
          <div className="mt-5 border-t border-tb-border pt-4">
            <p className="text-[10px] font-bold tracking-[0.2em] text-tb-subtle">
              SOURCES
            </p>
            <ul className="mt-2 space-y-2">
              {displayedSources.map((s, i) => (
                <li key={`${s.url}-${i}`} className="flex gap-2 text-sm">
                  <span className="shrink-0 rounded bg-tb-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-tb-subtle ring-1 ring-tb-border">
                    {sourceIcon(s.source_type)}
                  </span>
                  <div className="min-w-0 flex-1">
                    {isExpanded && s.url ? (
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-start gap-1 text-tb-text underline-offset-2 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span className="line-clamp-2">{s.title}</span>
                        <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-50" />
                      </a>
                    ) : (
                      <span className="line-clamp-2 text-tb-muted">{s.title}</span>
                    )}
                    {s.source_name ? (
                      <p className="text-[11px] text-tb-subtle">{s.source_name}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
            {more > 0 && !isExpanded ? (
              <p className="mt-2 text-[11px] text-tb-subtle">+{more} more in expanded view</p>
            ) : null}
          </div>
        ) : (
          <p className="mt-4 text-center text-[11px] text-tb-subtle">
            Curated from today&apos;s tech clusters
          </p>
        )}

        {onOpen && !isExpanded ? (
          <div className="mt-4 flex items-center justify-center gap-1 text-[11px] font-medium text-tb-subtle transition-colors duration-200 group-hover:text-tb-muted">
            Open
            <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
          </div>
        ) : null}
      </div>
    </div>
  );
});

FeedCard.displayName = "FeedCard";
