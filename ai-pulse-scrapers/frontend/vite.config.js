import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vite + React. Proxies /api to FastAPI on port 8000 during local dev.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
