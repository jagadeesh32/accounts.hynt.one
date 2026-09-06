import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// On localhost there is no parent domain to share a cookie across, so the dev
// server proxies the auth surface and the app stays same-origin. That proxy is
// what makes the cookie work at all in dev — see docs/RUNNING_LOCALLY.md.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5170,
    proxy: {
      "/api": { target: "http://127.0.0.1:9000", changeOrigin: true },
      "/oauth": { target: "http://127.0.0.1:9000", changeOrigin: true },
      "/.well-known": { target: "http://127.0.0.1:9000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
