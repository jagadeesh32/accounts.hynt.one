import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5170,
    strictPort: true,
    // Same-origin proxy in development. The SSO cookie is host-only on
    // localhost (there is no parent domain to share), so the API must appear on
    // the same origin as the app or the browser will not send it at all.
    proxy: {
      "/api": { target: "http://127.0.0.1:9000", changeOrigin: false },
      "/oauth": { target: "http://127.0.0.1:9000", changeOrigin: false },
      "/.well-known": { target: "http://127.0.0.1:9000", changeOrigin: false },
    },
  },
});
