# img2text — luật riêng của repo

Kế thừa `../AGENTS.md` (workspace) và `~/.pi/agent/AGENTS.md` (global). File này chỉ thêm
luật riêng, không lặp lại.

## UI review gate: Playwright là bằng chứng, taste skill là phán đoán

**Luật cứng:** không nói "UI đã sửa xong / đã đẹp hơn" khi chưa có (a) ảnh **sau** khi sửa ở
đúng viewport đã chụp **trước** khi sửa, và (b) `audit-a11y.mjs` không còn finding.

### 0. Chuẩn bị
- Dev stack: `docker compose -f deploy/docker-compose.dev.yml up -d` (API :8010) + `cd web && npm run dev` (:5173).
- Browser: `cd web && npx playwright install chromium` (chỉ lần đầu).
- Seed để audit: `cd web && node scripts/audit-shots.mjs register` → set `is_verified=true` cho user
  trong DB (SMTP down → row vẫn được tạo). Mode `shoot` dùng lại `/tmp/audit/seed.json`.

### 1. Chụp baseline — TRƯỚC khi sửa, đúng viewport sẽ dùng để verify
| Việc | Lệnh | Ra đâu |
|---|---|---|
| Mọi route × 4 width (320/768/1024/1440) | `cd web && node scripts/audit-shots.mjs shoot` | `/tmp/audit/<route>__<w>.png` |
| a11y: contrast / target <24px / alt / h1 / overflow, 8 route × 1440+320 | `cd web && npm run audit:a11y` | stdout |
| Ảnh landing thật (commit) | `cd web && node scripts/landing-shots.mjs` | `web/public/shots/` |

`audit-a11y.mjs` **không** exit khác 0 — gate là đọc dòng cuối `DONE N routes with findings` (N phải = 0).
Credentials: env `SHOT_EMAIL` / `SHOT_PASSWORD` (mặc định `admin@dev.local`).

### 2. Chấm — skill nào làm việc gì
- `ui-ux-review` → **owner của finding + verdict**: 4 pass (visual / responsive / a11y / code),
  format `severity | file:line — issue → fix`, tối đa 10, kết bằng
  APPROVED / APPROVED-WITH-NITS / CHANGES-REQUIRED. Gate này áp cho toàn app (editor, jobs, storage, admin).
- `design-taste-frontend` → **owner của hướng thẩm mỹ + pre-flight**: §0 design read, §1 dials,
  §11 audit-first khi là redesign, §14 FINAL PRE-FLIGHT là checklist cuối.
  §13 ghi rõ skill **out of scope** cho dashboard / dense product UI → chỉ áp cho `/` (Landing),
  surface marketing và phần polish thị giác; đừng bắt editor/admin "làm landing".
- `redesign-existing-projects` / `minimalist-ui` / `high-end-visual-design` → chỉ khi user chỉ định hướng.

Thứ tự bắt buộc: **chụp → ui-ux-review ra finding → design-taste định hướng fix → sửa → chụp lại → §14**.

### 3. Sửa
- Mỗi finding ↔ một thay đổi; không sửa code ngoài finding (kể cả "tiện tay" format lại).
- Màu / spacing lấy từ token, CSS var sẵn có của `web/src`, không thêm hex mới.

### 4. Verify — cùng viewport, so before/after
Chạy lại đúng script + đúng width ở bước 1; đọc ảnh (read tool đọc được PNG) và so với baseline;
`audit-a11y.mjs` phải về `DONE 0 routes with findings`, hoặc ghi rõ finding nào cố ý giữ + lý do.

### 5. Giới hạn vòng lặp
- 1 pass "taste rewrite" + tối đa 2 pass sửa lỗi. Quá → dừng, báo user, không tự đổi layout tiếp.
- Không mở rộng sang page không có trong finding.

### Playwright MCP (khi script không với tới)
`audit-a11y.mjs` phủ contrast / target / alt / h1 / overflow; `audit-shots.mjs` phủ ảnh.
Chưa phủ: click flow nhiều bước, `focus-visible` bằng bàn phím, aria-state sau tương tác.
Lúc đó thêm `pi mcp add -l playwright -- npx @playwright/mcp@latest`
(UNVERIFIED — chưa chạy trong repo này). Kết luận từ MCP cũng phải kèm URL + viewport + ảnh/snapshot.
