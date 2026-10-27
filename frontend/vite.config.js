import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // Small font subsets would otherwise be inlined as data: URLs, which the production CSP (font-src 'self')
    // blocks. Keep every font a file; other small assets may still be inlined.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_TARGET || "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    restoreMocks: true,
  },
});
