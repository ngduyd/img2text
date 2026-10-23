/**
 * Rà soát tự động a11y/target-size/overflow trên 8 route × 2 breakpoint.
 * Cần dev stack (vite :5173 + api :8010) + seed admin; chạy:
 *   node scripts/audit-a11y.mjs
 * Cờ: SHOT_EMAIL / SHOT_PASSWORD (mặc định admin@dev.local).
 * Kiểm: contrast <4.5:1 (3:1 cho chữ lớn), target <24px, <img> thiếu alt,
 * control không tên, >1 h1, tràn ngang. In ra route nào có vấn đề.
 */
import { chromium } from "playwright";

const ROUTES = ["/", "/jobs", "/jobs/5", "/jobs/5/text", "/jobs/5/layout", "/storage", "/profile", "/admin"];
const SIZES = [{ w: 1440, h: 900 }, { w: 320, h: 720 }];

const lum = (c) => {
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

const b = await chromium.launch({
  channel: "chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
const ctx = await b.newContext({ viewport: { width: SIZES[0].w, height: SIZES[0].h }, locale: "vi-VN" });
const p = await ctx.newPage();
const WEB = "http://localhost:5173";

// Login qua API (1 request/run) — tránh form + rate-limit 10/h của /auth/login.
const lr = await ctx.request.post(`${WEB}/api/auth/login`, {
  data: { email: process.env.SHOT_EMAIL ?? "admin@dev.local", password: process.env.SHOT_PASSWORD ?? "Audit-2024-pw" },
});
if (lr.status() !== 200) throw new Error(`login ${lr.status()}`);
await p.goto(`${WEB}/`, { waitUntil: "domcontentloaded", timeout: 60000 });
await p.evaluate(() => localStorage.setItem("lang", "vi"));

const findings = [];
for (const size of SIZES) {
  await p.setViewportSize({ width: size.w, height: size.h });
  for (const route of ROUTES) {
    await p.goto(`${WEB}${route}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await p.waitForTimeout(900);
    const r = await p.evaluate(() => {
      const parse = (s) => {
        const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
        return m ? { c: [+m[1], +m[2], +m[3]], a: m[4] === undefined ? 1 : +m[4] } : null;
      };
      const bgOf = (el) => {
        let n = el;
        while (n) {
          const bg = parse(getComputedStyle(n).backgroundColor);
          if (bg && bg.a > 0.5) return bg.c;
          n = n.parentElement;
        }
        return [0, 0, 0];
      };
      const out = { lowContrast: [], smallTargets: [], noAlt: [], overflowX: null, iconNoLabel: [], dupH1: 0 };
      const vis = (el) => {
        const s = getComputedStyle(el);
        return s.visibility !== "hidden" && s.display !== "none" && el.getBoundingClientRect().width > 0;
      };
      for (const el of document.querySelectorAll("p,span,a,li,td,label,h1,h2,h3,button,summary")) {
        if (!vis(el)) continue;
        const txt = (el.textContent || "").trim();
        if (!txt || el.children.length > 0) continue;
        const cs = getComputedStyle(el);
        const fg = parse(cs.color);
        if (!fg) continue;
        const bg = bgOf(el);
        const size = parseFloat(cs.fontSize);
        const bold = parseInt(cs.fontWeight, 10) >= 600;
        const large = size >= 24 || (size >= 18.66 && bold);
        const need = large ? 3 : 4.5;
        const L = (c) => {
          const norm = c.map((v) => {
            const s = v / 255;
            return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * norm[0] + 0.7152 * norm[1] + 0.0722 * norm[2];
        };
        const [hi, lo] = [L(fg.c), L(bg)].sort((x, y) => y - x);
        const rr = (hi + 0.05) / (lo + 0.05);
        if (rr < need) out.lowContrast.push(`${Math.round(rr * 100) / 100}:1 ${size}px "${txt.slice(0, 30)}"`);
      }
      for (const el of document.querySelectorAll("button,a[href],summary,input,select,textarea,[role=button]")) {
        if (!vis(el)) continue;
        const b = el.getBoundingClientRect();
        if (b.width < 24 || b.height < 24)
          out.smallTargets.push(`${Math.round(b.width)}x${Math.round(b.height)} ${el.tagName} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 20)}"`);
        const name = (el.getAttribute("aria-label") || el.textContent || "").trim();
        if (!name && !el.getAttribute("title")) out.iconNoLabel.push(el.outerHTML.slice(0, 70));
      }
      for (const img of document.querySelectorAll("img")) if (!img.hasAttribute("alt")) out.noAlt.push(img.src.slice(-40));
      out.dupH1 = document.querySelectorAll("h1").length;
      out.overflowX = document.documentElement.scrollWidth - window.innerWidth;
      return out;
    });
    if (r.lowContrast.length || r.smallTargets.length || r.noAlt.length || r.iconNoLabel.length || r.dupH1 > 1 || r.overflowX > 1)
      findings.push({ route, w: size.w, ...r });
  }
}
await b.close();
for (const f of findings) {
  console.log(`\n### ${f.route} @${f.w}`);
  if (f.overflowX > 1) console.log(`  overflow-x: +${f.overflowX}px`);
  if (f.dupH1 > 1) console.log(`  h1 count: ${f.dupH1}`);
  if (f.lowContrast.length) console.log("  low contrast:", [...new Set(f.lowContrast)].slice(0, 6).join(" | "));
  if (f.smallTargets.length) console.log("  small targets:", [...new Set(f.smallTargets)].slice(0, 6).join(" | "));
  if (f.noAlt.length) console.log("  img no alt:", f.noAlt.join(", "));
  if (f.iconNoLabel.length) console.log("  unlabeled control:", f.iconNoLabel[0]);
}
console.log("\nDONE", findings.length, "routes with findings");
