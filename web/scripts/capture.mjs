/**
 * Chụp screenshot tĩnh (playwright chromium headless, 1440x900) cho landing/gallery.
 * - Dev stack: vite dev port 5174 (tránh đè 5173), proxy /api -> localhost:8010
 *   (server container đã chạy). KHÔNG đăng nhập: Landing/Login/Register là trang
 *   công khai; /jobs redirect về /signin khi chưa auth (đủ cho gallery).
 * - Output: web/public/screenshots/*.png (Landing gallery đọc trực tiếp).
 * Dùng: node scripts/capture.mjs   (chạy trong web/)
 * LIMITATION (lane-d 2026-10-12): chromium khong chay duoc trong sandbox nay
 * (chrome --dump-dom cung treo, exit 124). Anh chua chup duoc: gallery dung
 * placeholder (onError an img, caption van doc). Chay lai script tren may co
 * display/chromium binh thuong de thay the placeholder.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(webRoot, "public", "screenshots");
const PORT = 5174;
const BASE = `http://localhost:${PORT}`;

const SHOTS = [
  { path: "/", name: "landing" },
  { path: "/signin", name: "login" },
  { path: "/signup", name: "register" },
  { path: "/jobs", name: "jobs-empty" }, // chưa auth -> redirect /signin (Jobs list trống khi login capture-only)
];

async function waitForServer(url, ms = 120_000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      /* vite chưa lên */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`vite dev khong len duoc ${url}`);
}

const dev = spawn("npx", ["vite", "--port", String(PORT), "--strictPort"], {
  cwd: webRoot,
  stdio: "ignore",
});

let browser;
try {
  await waitForServer(BASE);
  mkdirSync(outDir, { recursive: true });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  for (const shot of SHOTS) {
    await page.goto(BASE + shot.path, { waitUntil: "networkidle", timeout: 90_000 });
    await page.waitForTimeout(600); // motion entry + fonts settle
    const file = path.join(outDir, `${shot.name}.png`);
    await page.screenshot({ path: file });
    const kb = Math.round(statSync(file).size / 1024);
    console.log(`OK ${shot.name}.png ${kb}KB`);
  }
} finally {
  await browser?.close();
  dev.kill();
}
