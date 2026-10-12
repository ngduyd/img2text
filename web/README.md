# img2text — web

Frontend cho img2text: tải ảnh, chạy OCR, duyệt kết quả trích xuất (React + Vite + Tailwind).

Chạy dev server: `npm run dev`

Chạy test: `npm test`

Build sản xuất: `npm run build`

## Chụp screenshot landing

6 ảnh trong `public/screenshots/` (src của gallery `Landing.tsx`) được capture
bằng Playwright — **chạy tay trên máy bình thường** (sandbox chặn Chrome
network service, script không chạy được trong CI/sandbox).

Chuẩn bị:

1. Backend + worker (LLM) đang chạy (dev: `:8010`).
2. Dev server frontend: `npm run dev` (`:5173`).
3. Cài Chromium: `npx playwright install chromium`.

Chạy:

```sh
cd web
npm i
ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=... node scripts/capture.mjs
# hoặc: npm run capture
```

- Script tự seed: register email ngẫu nhiên → login (cookie context) → upload
  ảnh text thật → poll job `done` (LLM, có thể vài phút) → chụp từng trang.
- Step nào fail → log + continue, slot khác vẫn chụp.
- Slot admin (`admin-users.png`) cần env `ADMIN_EMAIL` + `ADMIN_PASSWORD`
  (admin bootstrap, spec R28); thiếu → skip + warning.
- Output khớp `GALLERY` trong `src/pages/Landing.tsx`: `landing-hero`, `login`,
  `jobdetail`, `layout-preview`, `export-menu`, `admin-users` (`.png`).
