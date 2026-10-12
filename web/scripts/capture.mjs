/**
 * Capture screenshots qua system Chrome headless CLI (playwright chromium treo
 * trong sandbox). App auth = httpOnly cookie (credentials:"include"), nên
 * script seed cookie bằng mini-server :8888 redirect sang :5174 kèm Set-Cookie
 * (cùng host localhost → cookie áp dụng cho vite dev).
 * Yêu cầu: server backend :8010 + chạy `node scripts/capture.mjs` (tự spawn vite :5174).
 */
import { spawn } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { setTimeout as sleep } from "node:timers/promises";

const PORT = 5174;
const BASE = `http://localhost:${PORT}`;
const API = "http://localhost:8010";
const SEED_PORT = 8888;
const OUT = "public/screenshots";
const CHROME = process.env.CHROME_BIN || "google-chrome";
const AUTH = { email: "capture@example.com", password: "Capture-2024-pw" };

// auth:true → đi qua seed server để nhận cookie rồi redirect về trang thật.
const SHOTS = [
  { path: "/", name: "landing-hero" },
  { path: "/signin", name: "signin" },
  { path: "/signup", name: "signup" },
  { path: "/jobs", name: "jobs-list", auth: true },
  { path: "/jobs/1/extraction", name: "extraction", auth: true },
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

/** Shot viewport cao — thấy cả 2 section (Văn bản + Layout) của JobDetail. */
function chromeShotTall(url, file) {
  return chromeShot(url, file, { height: 2600 });
}
function chromeShot(url, file, opts = {}) {
  return new Promise((resolve, reject) => {
    const args = [
      "--headless=new",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      `--screenshot=${file}`,
      `--window-size=1440,${opts.height || 900}`,
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

/** Đăng nhập (fallback register) qua backend :8010 → lấy Set-Cookie headers. */
async function authCookies() {
  const body = JSON.stringify(AUTH);
  const opts = { method: "POST", headers: { "Content-Type": "application/json" }, body };
  let res = await fetch(`${API}/api/auth/login`, opts);
  if (!res.ok) res = await fetch(`${API}/api/auth/register`, opts);
  if (!res.ok) throw new Error(`auth ${AUTH.email} fail: HTTP ${res.status}`);
  return res.headers.getSetCookie();
}

/** Mini-server: mỗi request redirect về trang đích trên :5174, re-emit cookie auth. */
function startSeed(cookies) {
  const srv = createServer((req, res) => {
    const target = req.url === "/" ? "/jobs" : req.url;
    res.writeHead(302, { Location: BASE + target, "Set-Cookie": cookies });
    res.end();
  });
  srv.listen(SEED_PORT);
  return srv;
}

/** Job 1 có thật không (cần ảnh đã upload) — không có thì bỏ slot jobdetail. */
async function jobExists(cookieHeader) {
  const res = await fetch(`${API}/api/jobs/1`, { headers: { Cookie: cookieHeader } });
  return res.ok;
}

const dev = spawn("npx", ["vite", "--port", String(PORT), "--strictPort"], {
  stdio: "ignore",
});
try {
  mkdirSync(OUT, { recursive: true });
  const cookies = await authCookies();
  const seed = startSeed(cookies);
  await waitForServer(BASE);
  for (const s of SHOTS) {
    const url = s.auth ? `http://localhost:${SEED_PORT}${s.path}` : BASE + s.path;
    await chromeShot(url, `${OUT}/${s.name}.png`);
    console.log("shot:", `${OUT}/${s.name}.png`);
  }
  // jobdetail-vanban/layout: cần job thật (đã upload ảnh). Không có → bỏ qua.
  const cookieHeader = cookies.map((c) => c.split(";")[0]).join("; ");
  if (await jobExists(cookieHeader)) {
    await chromeShot(
      `http://localhost:${SEED_PORT}/jobs/1`,
      `${OUT}/jobdetail-vanban.png`,
    );
    console.log("shot:", `${OUT}/jobdetail-vanban.png`);
    // jobdetail-layout: cùng trang /jobs/1 nhưng khung Layout nằm DƯỚI section
    // Văn bản → viewport cao (1440x2600) để thấy cả 2 section trong 1 ảnh.
    await chromeShotTall(
      `http://localhost:${SEED_PORT}/jobs/1`,
      `${OUT}/jobdetail-layout.png`,
    );
    console.log("shot:", `${OUT}/jobdetail-layout.png`);
  } else {
    console.log("skip: jobdetail-*.png — chưa có job thật, upload ảnh trước rồi chạy lại");
  }
  console.log("DONE →", OUT);
  seed.close();
} catch (e) {
  console.error("capture failed:", e.message);
  process.exitCode = 1;
} finally {
  dev.kill("SIGTERM");
}
