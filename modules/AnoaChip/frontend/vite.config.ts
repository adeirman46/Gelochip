import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI backend (uvicorn). AnoaChip's backend runs
// on :8012 so it can coexist with a GarudaChip instance on :8011.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      "/api": {
        target: "http://localhost:8012",
        changeOrigin: true,
      },
    },
  },
});
