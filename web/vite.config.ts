/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Truy cập dev qua Tailscale/LAN (server không chạy trên máy user): Vite 6+
    // chặn Host lạ để tránh DNS-rebinding → khai báo rõ host được phép.
    allowedHosts: [".ts.net", "100.86.205.2", "nguyenducduy-server"],
    // dev: vite proxy same-origin; server also has CORS regex middleware for
    // forwarded origins (Plan X; prod nginx handles /api/ instead). Target =
    // compose dev host port (DEV_PORT override in deploy/docker-compose.dev.yml
    // — keep in sync).
    proxy: { "/api": "http://localhost:8010" },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
