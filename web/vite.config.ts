/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // dev: SPA same-origin via vite proxy (no CORS middleware on server;
    // prod nginx handles /api/ instead). Target = compose dev host port
    // (DEV_PORT override in deploy/docker-compose.dev.yml — keep in sync).
    proxy: { "/api": "http://localhost:8010" },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
