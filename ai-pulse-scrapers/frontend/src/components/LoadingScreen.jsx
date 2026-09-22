/**
 * Short branded intro while the stored feed loads.
 * Subtle motion only; respects prefers-reduced-motion.
 */
export function LoadingScreen({ fading = false }) {
  return (
    <div
      className={[
        "flex min-h-[100dvh] flex-col items-center justify-center bg-tb-bg px-6 text-center text-tb-text",
        "transition-opacity duration-500 ease-out",
        fading ? "opacity-0" : "opacity-100",
        "motion-safe:animate-intro-in",
      ]
        .filter(Boolean)
        .join(" ")}
      role="status"
      aria-live="polite"
      aria-busy={!fading}
    >
      <p className="text-3xl font-bold tracking-tight sm:text-4xl">TechBytes</p>
      <p className="mt-3 text-base text-tb-muted sm:text-lg">Preparing your content</p>
      <div
        className="mt-8 h-1.5 w-28 overflow-hidden rounded-full bg-tb-surface-2 ring-1 ring-tb-border"
        aria-hidden
      >
        <div className="h-full w-1/2 rounded-full bg-tb-text/70 motion-safe:animate-intro-bar" />
      </div>
    </div>
  );
}
