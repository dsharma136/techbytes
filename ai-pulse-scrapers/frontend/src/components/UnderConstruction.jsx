import { Construction } from "lucide-react";

/**
 * Production placeholder while the full feed UI is being fixed.
 * Rendered as a modal-style popup so the status is unmistakable on deploy.
 */
export function UnderConstruction() {
  return (
    <div className="relative min-h-screen bg-neutral-950 font-sans text-neutral-100 antialiased">
      <div
        className="pointer-events-none absolute inset-0 bg-black/55"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            "radial-gradient(ellipse 70% 45% at 50% 35%, rgba(99,102,241,0.12), transparent 55%)",
        }}
        aria-hidden
      />

      <main className="relative z-10 mx-auto flex min-h-[100dvh] w-full max-w-[375px] flex-col items-center justify-center px-5 py-16 sm:max-w-md">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="uc-title"
          aria-describedby="uc-desc"
          className="animate-card-in w-full rounded-2xl border border-neutral-700/80 bg-neutral-900 p-7 text-center shadow-[0_24px_80px_-16px_rgba(0,0,0,0.95)] ring-1 ring-white/[0.06] sm:p-8"
        >
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-300 ring-1 ring-amber-400/25">
            <Construction className="h-6 w-6" aria-hidden />
          </div>

          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300/90">
            Under construction
          </p>

          <h1
            id="uc-title"
            className="mt-2 text-2xl font-bold tracking-tight text-neutral-50"
          >
            TechBytes
          </h1>

          <p id="uc-desc" className="mt-3 text-sm leading-relaxed text-neutral-300">
            Daily micro-learning cards on what matters in AI and tech.
          </p>

          <p className="mt-5 text-sm leading-relaxed text-neutral-400">
            We are fixing a few issues and launching again soon. Thanks for your
            patience.
          </p>
        </div>
      </main>
    </div>
  );
}
