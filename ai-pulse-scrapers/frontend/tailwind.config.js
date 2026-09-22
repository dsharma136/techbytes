/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        tb: {
          bg: "var(--tb-bg)",
          surface: "var(--tb-surface)",
          "surface-2": "var(--tb-surface-2)",
          border: "var(--tb-border)",
          "border-strong": "var(--tb-border-strong)",
          text: "var(--tb-text)",
          muted: "var(--tb-text-muted)",
          subtle: "var(--tb-text-subtle)",
          accent: "var(--tb-accent)",
          "accent-fg": "var(--tb-accent-fg)",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "Inter var",
          "ui-sans-serif",
          "system-ui",
          "Segoe UI",
          "sans-serif",
        ],
      },
      maxWidth: {
        shell: "1200px",
      },
      keyframes: {
        "card-in": {
          from: {
            opacity: "0",
            transform: "translateY(10px)",
          },
          to: {
            opacity: "1",
            transform: "translateY(0)",
          },
        },
      },
      animation: {
        "card-in": "card-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};
