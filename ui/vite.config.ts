/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

import { contentSecurityPolicy } from "./plugins/csp.ts";

// The desktop app loads the production build over file://, where module scripts can't load
// other files, so the build is a single self-contained index.html (see PLAN.md 10: no local
// web server). Dev mode serves from Vite with hot reload instead.
export default defineConfig({
  plugins: [react(), viteSingleFile({ removeViteModuleLoader: true }), contentSecurityPolicy()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    reportCompressedSize: false,
    chunkSizeWarningLimit: 4096,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "plugins/**/*.test.ts"],
    restoreMocks: true,
  },
});
