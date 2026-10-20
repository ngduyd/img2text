/**
 * Audit screenshots — designer pass.
 *   node scripts/audit-shots.mjs register   # tạo user (SMTP down → 503, row vẫn có)
 *   # → verify trong DB: UPDATE users SET is_verified=true
 *   node scripts/audit-shots.mjs shoot      # login + upload 3 job + chụp mọi route
 * Output: /tmp/audit/<route>__<width>.png
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { chromium } from "playwright";

const WEB = "http://localhost:5173";
const OUT = "/tmp/audit";
const WIDTHS = [320, 768, 1024, 1440];
const PASSWORD = "Audit-2024-pw";
const MODE = process.argv[2] || "shoot";
const SEED_FILE = `${OUT}/seed.json`;

const stamp = Date.now();
const fresh = () => ({
  user: { email: `audit-${stamp}@example.com`, password: PASSWORD },
  admin: { email: `audit-adm-${stamp}@example.com`, password: PASSWORD },
});
if (!existsSync(SEED_FILE)) {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(SEED_FILE, JSON.stringify(fresh(), null, 2));
}
const SEED = JSON.parse(readFileSync(SEED_FILE, "utf8"));

// PNG 1x1 — job sẽ pending, đủ để xem layout list/detail
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
  "base64",
);
// PDF hợp lệ tối thiểu (1 trang trắng)
const PDF = Buffer.from(
  `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj
trailer<</Root 1 0 R>>
%%EOF`,
  "utf8",
);
const sha256 = (b) => createHash("sha256").update(b).digest("hex");

const LAUNCH = {
  channel: "chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process", "--no-zygote"],
};

async function api(ctx, method, path, data) {
  const r = await ctx.request.fetch(`${WEB}${path}`, { method, data });
  return { ok: r.ok(), status: r.status(), body: await r.text() };
}

const ROUTES = (jobId) => [
  ["landing", "/"], ["signin", "/signin"], ["signup", "/signup"],
  ["forgot", "/forgot"], ["features", "/features"], ["jobs", "/jobs"],
  ["jobdetail", jobId && `/jobs/${jobId}`], ["extraction", jobId && `/jobs/${jobId}/extraction`],
  ["storage", "/storage"], ["profile", "/profile"], ["feedback", "/feedback"], ["admin", "/admin"],
];

async function register(browser) {
  const ctx = await browser.newContext();
  for (const [label, cred] of [["user", SEED.user], ["admin", SEED.admin]]) {
    const r = await api(ctx, "POST", "/api/auth/register", cred);
    console.log(`register ${label}: ${r.status} ${r.body.slice(0, 100)}`);
  }
  await ctx.close();
  console.log("\nGiờ verify trong DB:\n  docker exec img2text-dev-postgres-1 psql -U img2text -d img2text_dev -c \"UPDATE users SET is_verified=true WHERE email LIKE 'audit-%'\"");
}

async function shoot(browser) {
  const user = await browser.newContext();
  let r = await api(user, "POST", "/api/auth/login", SEED.user);
  console.log(`login user: ${r.status}`);
  if (!r.ok) throw new Error(`login failed — chạy 'register' + verify DB trước`);

  const jobs = [];
  for (const [name, ct, buf] of [
    ["hoa-don-1.png", "image/png", PNG],
    ["hop-dong.pdf", "application/pdf", PDF],
    ["bang-luong.png", "image/png", PNG],
  ]) {
    const pre = await api(user, "POST", "/api/jobs/presign", {
      filename: name,
      content_type: ct,
      size_bytes: buf.length,
      sha256: sha256(buf),
      page_count: 1,
      output_format: "md",
      mode: "layout",
    });
    if (!pre.ok) { console.log(`presign ${name}: ${pre.status} ${pre.body.slice(0, 140)}`); continue; }
    const p = JSON.parse(pre.body);
    const put = await fetch(p.url, { method: "PUT", body: buf, headers: { "content-type": ct } }).catch(() => null);
    if (!put?.ok) console.log(`PUT ${name}: ${put?.status}`);
    const cj = await api(user, "POST", "/api/jobs", {
      storage_key: p.storage_key,
      page_count: 1,
      filename: name,
      output_format: "md",
      mode: "layout",
    });
    if (cj.ok) jobs.push(JSON.parse(cj.body).id);
    else console.log(`create ${name}: ${cj.status} ${cj.body.slice(0, 160)}`);
  }
  console.log("jobs created:", jobs);

  const adminCtx = await browser.newContext();
  let al = await api(adminCtx, "POST", "/api/auth/login", SEED.admin);
  if (al.status === 429) {
    console.log("admin 429 — chờ 60s");
    await new Promise((r) => setTimeout(r, 60000));
    al = await api(adminCtx, "POST", "/api/auth/login", SEED.admin);
  }
  console.log(`login admin: ${al.status}`);

  const state = await user.storageState();
  const adminState = await adminCtx.storageState();

  for (const [name, path] of ROUTES(jobs[0])) {
    if (!path) continue;
    const isAdmin = name === "admin";
    for (const w of WIDTHS) {
      const ctx = await browser.newContext({ viewport: { width: w, height: 900 } });
      await ctx.addCookies((isAdmin ? adminState : state).cookies);
      const page = await ctx.newPage();
      const errs = [];
      page.on("pageerror", (e) => errs.push(String(e).slice(0, 120)));
      try {
        await page.goto(`${WEB}${path}`, { waitUntil: "networkidle", timeout: 30000 });
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${OUT}/${name}__${w}.png`, fullPage: true });
        const m = await page.evaluate(() => ({
          ov: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          h: document.documentElement.scrollHeight,
          btns: document.querySelectorAll("button, a[role=button]").length,
          links: document.querySelectorAll("a").length,
        }));
        console.log(`${name}@${w} ovX=${m.ov} h=${m.h} btns=${m.btns} links=${m.links}${errs.length ? ` ERR:${errs[0]}` : ""}`);
      } catch (e) {
        console.log(`${name}@${w} FAIL ${String(e).split("\n")[0].slice(0, 100)}`);
      }
      await ctx.close();
    }
  }
  await user.close();
  await adminCtx.close();
}

const browser = await chromium.launch(LAUNCH);
try {
  if (MODE === "register") await register(browser);
  else await shoot(browser);
} finally {
  await browser.close();
}
