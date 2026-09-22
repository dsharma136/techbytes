import { CATEGORY_ORDER, pillForSlug } from "../constants/categories.js";



/**

 * Scrollable category pills for non-empty categories only (no "All").

 * Extra padding + inset rings so active rings are never clipped by overflow-x.

 */

export function CategoryFilter({ categories, activeCategory, onFilter }) {

  if (!categories || categories.length === 0) {

    return null;

  }



  const defs = categories

    .map((slug) => CATEGORY_ORDER.find((p) => p.slug === slug) || pillForSlug(slug))

    .filter(Boolean);



  return (

    <div className="border-b border-tb-border py-2.5">

      <div className="flex max-w-full gap-2.5 overflow-x-auto overscroll-x-contain px-2 py-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">

        {defs.map((def) => {

          const active = activeCategory === def.slug;

          const style = active ? def.active : def.inactive;

          return (

            <button

              key={def.slug}

              type="button"

              onClick={() => onFilter(def.slug)}

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


