import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production build is emitted into app/static/web/, which the FastAPI backend
// serves at "/". In dev (`npm run dev`) Vite proxies the API/asset routes to
// the running backend on :8090 so the SPA and agent talk over the same origin.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../static/web",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8090", changeOrigin: true },
      "/output": { target: "http://localhost:8090", changeOrigin: true },
      "/datasets": { target: "http://localhost:8090", changeOrigin: true },
    },
  },
});
