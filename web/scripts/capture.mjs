/**
 * Capture 6 screenshot landing (spec §User-facing #8) bằng Playwright Chromium.
 * CHẠY TAY trên máy bình thường — sandbox chặn Chrome network service.
 *
 * Yêu cầu: backend :8010 + worker (LLM) + vite dev :5173 đang chạy.
 *   cd web && npm i && npx playwright install chromium && node scripts/capture.mjs
 *
 * Seed: POST /api/auth/register (email ngẫu nhiên) → cookie session của context.
 * Admin slot: cần env ADMIN_EMAIL + ADMIN_PASSWORD (bootstrap admin, spec R28);
 * không có → skip + warning.
 *
 * Graceful: step nào fail → log + continue (slot còn lại vẫn chụp).
 * Output: web/public/screenshots/{landing-hero,login,jobdetail,layout-preview,export-menu,admin-users}.png
 *        khớp src của GALLERY trong src/pages/Landing.tsx.
 */
import { createHash } from "node:crypto";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const WEB = process.env.CAPTURE_WEB || "http://localhost:5173";
const OUT = "public/screenshots";
const JOB_POLL_MS = 300_000; // LLM OCR+layout — 5 phút rồi skip
const AUTH = {
  email: `capture-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`,
  password: "Capture-2024-pw",
};

/** 1x1 JPEG — dùng làm template, nhưng upload ảnh THẬT (trang text render sẵn
 *  bằng chính chromium) để OCR ra nội dung có nghĩa trong screenshot. */

async function register(context) {
  const res = await context.request.post(`${WEB}/api/auth/register`, {
    data: AUTH,
  });
  if (!res.ok()) throw new Error(`register HTTP ${res.status()}`);
  // register đã Set-Cookie; login lại để chắc session (spec: register → login).
  const login = await context.request.post(`${WEB}/api/auth/login`, {
    data: AUTH,
  });
  if (!login.ok()) throw new Error(`login HTTP ${login.status()}`);
}

/** Upload 1 ảnh jpg (presign → PUT → create job) → id job. */
async function uploadFixture(context, bytes, filename) {
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  const presign = await context.request.post(`${WEB}/api/jobs/presign`, {
    data: {
      filename,
      content_type: "image/jpeg",
      size_bytes: bytes.length,
      sha256,
    },
  });
  if (!presign.ok()) throw new Error(`presign HTTP ${presign.status()}`);
  const { url, storage_key } = await presign.json();
  const put = await context.request.put(url, {
    data: bytes,
    headers: { "content-type": "image/jpeg" },
  });
  if (!put.ok()) throw new Error(`PUT presign HTTP ${put.status()}`);
  const job = await context.request.post(`${WEB}/api/jobs`, {
    data: { storage_key, page_count: 1, filename },
  });
  if (!job.ok()) throw new Error(`create job HTTP ${job.status()}`);
  return (await job.json()).id;
}

/** Poll job tới done (cần worker + LLM thật). failed/timeout → ném lỗi. */
async function waitDone(context, id) {
  const deadline = Date.now() + JOB_POLL_MS;
  while (Date.now() < deadline) {
    const res = await context.request.get(`${WEB}/api/jobs/${id}`);
    if (!res.ok()) throw new Error(`get job HTTP ${res.status()}`);
    const job = await res.json();
    if (job.status === "done") return;
    if (job.status === "failed")
      throw new Error(`job ${id} failed: ${job.error || "?"}`);
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(`job ${id} chưa done sau ${JOB_POLL_MS / 1000}s`);
}

/** Render 1 trang html có chữ tiếng Việt → buffer JPEG (fixture OCR thật). */
async function fixtureJpg(browser) {
  const page = await browser.newPage({ viewport: { width: 1024, height: 768 } });
  await page.setContent(`<!doctype html><html lang="vi"><body
    style="font:600 28px/1.6 system-ui;padding:48px;background:#fff;color:#111">
    <h1>Báo cáo doanh thu quý I</h1>
    <p>Doanh thu tăng 18% so với cùng kỳ năm trước.</p>
    <p>Chi phí vận hành giảm 7% nhờ tự động hóa quy trình.</p>
    <table style="border-collapse:collapse"><tr><td
      style="border:1px solid #999;padding:8px">Khu vực</td><td
      style="border:1px solid #999;padding:8px">Doanh thu</td></tr>
    <tr><td style="border:1px solid #999;padding:8px">Miền Bắc</td>
      <td style="border:1px solid #999;padding:8px">12 tỷ</td></tr></table>
  </body></html>`);
  const buf = await page.screenshot({ type: "jpeg", quality: 90 });
  await page.close();
  return buf;
}

/** Admin slot: đăng nhập ADMIN_EMAIL/ADMIN_PASSWORD (R28 bootstrap) → /admin
 *  → tab Users. Thiếu env hoặc 401 → skip + warning. */
async function captureAdmin(browser) {
  const email = process.env.ADMIN_EMAIL;
  const password = process.env.ADMIN_PASSWORD;
  if (!email || !password) {
    console.warn("skip admin-users: thiếu ADMIN_EMAIL/ADMIN_PASSWORD");
    return;
  }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  try {
    const login = await ctx.request.post(`${WEB}/api/auth/login`, {
      data: { email, password },
    });
    if (!login.ok()) throw new Error(`login admin HTTP ${login.status()}`);
    const page = await ctx.newPage();
    await page.goto(`${WEB}/admin`, { waitUntil: "networkidle" });
    await page.getByTestId("tab-users").click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/admin-users.png` });
    console.log("shot:", `${OUT}/admin-users.png`);
  } finally {
    await ctx.close();
  }
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Hero — full page 1440x900 (fullPage = toàn bộ landing).
  try {
    await register(context);
    await page.goto(WEB, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${OUT}/landing-hero.png`, fullPage: true });
    console.log("shot:", `${OUT}/landing-hero.png`);
  } catch (e) {
    console.warn("skip landing-hero:", e.message);
  }

  // 2. Login (route thật = /signin).
  try {
    await page.goto(`${WEB}/signin`, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${OUT}/login.png` });
    console.log("shot:", `${OUT}/login.png`);
  } catch (e) {
    console.warn("skip login:", e.message);
  }

  // 3-5. JobDetail: cần 1 job done — upload ảnh text thật → poll worker.
  let jobId = null;
  try {
    const bytes = await fixtureJpg(browser);
    jobId = await uploadFixture(context, bytes, "bao-cao-quy.jpg");
    console.log(`job ${jobId} queued — poll tới done (LLM, có thể vài phút)…`);
    await waitDone(context, jobId);
    console.log(`job ${jobId} done`);
  } catch (e) {
    console.warn("skip jobdetail slots:", e.message);
  }

  if (jobId !== null) {
    // 3. JobDetail 2 section — fullPage thấy cả Văn bản + Layout.
    try {
      await page.goto(`${WEB}/jobs/${jobId}`, { waitUntil: "networkidle" });
      await page.getByTestId("section-layout").scrollIntoViewIfNeeded();
      await page.waitForTimeout(400); // ảnh lazy-load trong 2 section
      await page.screenshot({ path: `${OUT}/jobdetail.png`, fullPage: true });
      console.log("shot:", `${OUT}/jobdetail.png`);
    } catch (e) {
      console.warn("skip jobdetail:", e.message);
    }

    // 4. Layout preview — viewport dồn vào section Layout.
    try {
      await page.getByTestId("section-layout").scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${OUT}/layout-preview.png` });
      console.log("shot:", `${OUT}/layout-preview.png`);
    } catch (e) {
      console.warn("skip layout-preview:", e.message);
    }

    // 5. Export menu mở — cả 2 nhóm "Văn bản" + "Layout".
    try {
      await page.getByTestId("export-more").click();
      await page.getByTestId("export-layout-more").click();
      await page.getByTestId("export-bar").scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await page.getByTestId("export-bar").screenshot({ path: `${OUT}/export-menu.png` });
      console.log("shot:", `${OUT}/export-menu.png`);
    } catch (e) {
      console.warn("skip export-menu:", e.message);
    }
  }

  // 6. Admin users.
  try {
    await captureAdmin(browser);
  } catch (e) {
    console.warn("skip admin-users:", e.message);
  }

  await context.close();
  console.log("DONE →", OUT);
} finally {
  await browser.close();
}
