import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// On localhost there is no parent domain to share a cookie across, so the dev
// server proxies the auth surface and the app stays same-origin. That proxy is
// what makes the cookie work at all in dev — see docs/RUNNING_LOCALLY.md.
// Vite drops extra attributes when it rewrites the entry script into the hashed
// bundle tag, so the data-cfasync="false" in index.html does not survive the
// build. Re-add it afterwards. Cloudflare Rocket Loader otherwise takes the
// module script, gives it a nonsense MIME type and re-executes it on its own
// schedule — which it does not do reliably for ES modules. On this host that is
// the sign-in page for the whole estate.
const cfasync = {
  name: "hynt-cfasync-opt-out",
  enforce: "post" as const,
  transformIndexHtml(html: string) {
    return html.replace(/<script(?![^>]*\bdata-cfasync=)/g, '<script data-cfasync="false"');
  },
};

export default defineConfig({
  plugins: [react(), cfasync],
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
