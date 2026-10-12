/**
 * Capture landing screenshots via system Chrome headless CLI
 * (playwright chromium treo trong sandbox — dùng google-chrome --headless=new).
 * Chạy: node scripts/capture.mjs   (cần web dev server hoặc tự spawn vite :5174)
 */
import { spawn } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const PORT = 5174;
const BASE = `http://localhost:${PORT}`;
const OUT = "public/screenshots";
const CHROME = process.env.CHROME_BIN || "google-chrome";

const SHOTS = [
  { path: "/", name: "landing-hero" },
  { path: "/login", name: "login" },
  { path: "/register", name: "register" },
  { path: "/jobs", name: "jobs" },
];

function waitForServer(url, tries = 60) {
  return (async () => {
    for (let i = 0; i < tries; i++) {
      try {
        const r = await fetch(url);
        if (r.ok) return;
      } catch {}
      await sleep(500);
    }
    throw new Error(`vite không lên ${url}`);
  })();
}

function chromeShot(url, file) {
  return new Promise((resolve, reject) => {
    const args = [
      "--headless=new",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      `--screenshot=${file}`,
      "--window-size=1440,900",
      "--hide-scrollbars",
      "--virtual-time-budget=10000",
      url,
    ];
    const p = spawn(CHROME, args, { stdio: "ignore" });
    p.on("exit", (code) => {
      // chrome exit != 0 vẫn có thể đã ghi file (network-service noise) — check file
      try {
        if (statSync(file).size > 10_000) return resolve();
      } catch {}
      reject(new Error(`chrome shot fail ${file} code=${code}`));
    });
  });
}

const dev = spawn("npx", ["vite", "--port", String(PORT), "--strictPort"], {
  stdio: "ignore",
});
try {
  mkdirSync(OUT, { recursive: true });
  await waitForServer(BASE);
  for (const s of SHOTS) {
    const file = `${OUT}/${s.name}.png`;
    await chromeShot(BASE + s.path, file);
    console.log("shot:", file);
  }
  console.log("DONE", SHOTS.length, "screenshots →", OUT);
} catch (e) {
  console.error("capture failed:", e.message);
  process.exitCode = 1;
} finally {
  dev.kill("SIGTERM");
}
