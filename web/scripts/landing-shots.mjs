/**
 * Chụp ảnh sản phẩm cho Landing (web/public/shots/).
 *
 * Chạy khi dev stack đã bật (vite :5173) và có sẵn user + job done:
 *   node scripts/landing-shots.mjs
 *
 * ponytail: dùng đúng job #5 (docx, done) đang seed trong DB dev thay vì tạo
 * job mới — worker trên Colab không chạy nên job mới sẽ mãi "Queued", ảnh
 * landing sẽ xấu. Nâng cấp: cho phép truyền JOB_ID/USER/PASSWORD qua env.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const WEB = "http://localhost:5173";
const OUT = join(process.cwd(), "public", "shots");
const JOB = process.env.JOB_ID ?? "5";
const EMAIL = process.env.SHOT_EMAIL ?? "admin@dev.local";
const PASSWORD = process.env.SHOT_PASSWORD ?? "Audit-2024-pw";
const LOGIN = {
  email: 'input[type="email"]',
  password: 'input[type="password"]',
  submit: 'button[type="submit"]',
};

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process", "--no-zygote"],
});
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 1.5,
});
const page = await ctx.newPage();

await page.goto(`${WEB}/signin`);
await page.evaluate(() => localStorage.setItem("lang", "vi"));
await page.goto(`${WEB}/signin`);
await page.fill(LOGIN.email, EMAIL);
await page.fill(LOGIN.password, PASSWORD);
await page.click(LOGIN.submit);
await page.waitForURL(/\/jobs/, { timeout: 20000 });

/** Chờ ảnh/font/preview ổn định rồi chụp jpeg (nhẹ hơn png cho landing). */
async function shot(name, path, prepare) {
  await page.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
  if (prepare) await prepare();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: join(OUT, `${name}.jpg`), type: "jpeg", quality: 84 });
  console.log(`shot ${name} ← ${path}`);
}

// 1. Jobs list — 1 CTA, hàng gọn, ⋯ menu.
await shot("jobs", "/jobs");

// 2. Editor + xem trước A4 (điểm bán hàng chính) — chờ paged.js chia trang xong.
await shot("editor", `/jobs/${JOB}/layout`, async () => {
  await page.waitForSelector('[data-testid="btn-edit-doc"]', { timeout: 20000 });
  await page.click('[data-testid="btn-edit-doc"]');
  await page.waitForSelector('[data-testid="page-preview"]', { timeout: 20000 });
  await page.waitForFunction(
    () => (document.querySelector('[data-testid="page-count"]')?.textContent ?? "").trim() !== "–",
    { timeout: 20000 },
  );
  await page.waitForTimeout(1500);
});

// 3. Trang Văn bản — OCR text + ảnh gốc đối chiếu.
await shot("text", `/jobs/${JOB}/text`);

await browser.close();
console.log(`xong → ${OUT}`);
