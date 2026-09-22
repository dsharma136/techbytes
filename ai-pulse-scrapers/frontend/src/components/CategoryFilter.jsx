import { CATEGORY_PILLS, GENERAL_PILL } from "../constants/categories.js";

const ALL = {
  slug: "all",
  label: "All",
  inactive:
    "bg-neutral-800/70 text-neutral-300 ring-1 ring-neutral-700/50 hover:bg-neutral-800",
  active:
    "bg-neutral-100 text-neutral-950 ring-2 ring-neutral-300 shadow-[0_0_16px_-4px_rgba(255,255,255,0.2)]",
};

const ROW = [ALL, ...CATEGORY_PILLS, GENERAL_PILL];

/**
 * Scrollable category pills with per-topic colors.
 */
export function CategoryFilter({ activeCategory, onFilter }) {
  return (
    <div className="border-b border-neutral-800/90 px-3 py-2.5">
      <div className="flex max-w-full gap-2 overflow-x-auto overscroll-x-contain pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {ROW.map((def) => {
          const slug = def.slug === "all" ? null : def.slug;
          const isAll = def.slug === "all";
          const active = isAll
            ? activeCategory == null
            : activeCategory === def.slug;
          const style = active ? def.active : def.inactive;
          return (
            <button
              key={def.slug}
              type="button"
              onClick={() => onFilter(isAll ? "all" : def.slug)}
              className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold tracking-tight transition-all duration-200 active:scale-[0.97] ${style}`}
            >
              {def.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
