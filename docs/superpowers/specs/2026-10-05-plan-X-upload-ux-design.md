# Plan X — Upload UX + Reliability (Design Spec)

## Problem (user feedback 2026-10-05)

1. CORS blocks upload through VSCode port-forwarding (server has NO CORS middleware; dev relies on vite proxy same-origin — forwarded origins bypass it).
2. Upload success/failure invisible: no toast, no navigation — user cannot tell if anything happened.
3. Jobs sit "Chờ xử lý" up to SCHEDULER_INTERVAL after upload; nothing nudges processing.
4. ImageCropWizard shows 2 images (`<img>` preview + `<canvas>`); forces rect selection (should default to full image); text toolbar below canvas (should be icons ON TOP with hover tooltips).
5. Admin UI layout weak; audit log lacks IP/User-Agent. Stats: later (explicit).

## Decisions (approved)

- **R58**: Scheduler interval = admin env config `SCHEDULER_INTERVAL_SECONDS` (default 60). Upload → worker poll kế tiếp (≤30s) xử lý (kick reaper bị xóa — R58a, reaper≠claim); realtime dispatch = bản trả phí/production.
- **R59**: Toast library (sonner) wired to EVERY api mutation — success + failure messages for all actions. Upload success → toast + navigate to /jobs (file list visible).
- **R60**: Admin UI redone per ui-ux skill (nav, table layout, badges); audit entries record client IP + User-Agent. Stats deferred.
- **R61**: Image tools = icon buttons, `title` tooltip shows tool name on hover ("Xoay 90°", "Xóa vùng chọn", "Gửi lên"); toolbar ABOVE canvas.
- **R62**: Crop wizard default = NO rect → submit original File untouched (no crop call, no error).

## Requirements

### Server
- CORS middleware (Starlette CORSMiddleware): allowed origins = regex list from env `ALLOWED_ORIGINS` (comma-separated regexes), default covers `http://localhost:*`, `http://127.0.0.1:*`, `https://[a-z0-9-]+\.vscode\.dev` (subdomain-anchored; `evilvscode.dev` rejected — R58 review); allow_credentials=True; safe methods/headers. Prod nginx same-origin unaffected.
- `SCHEDULER_INTERVAL_SECONDS` env (int, default 60, floor 5) read into settings.
- POST /jobs success → spawn background asyncio task that runs one scheduler claim attempt (same `_claim_lock` path; failure logged, never crashes request). Response unchanged (201 immediately).
- Audit entries (jobs + auth routers + admin actions): ip = X-Forwarded-For RIGHTMOST (Ruling R5 anti-spoof, pinned test_net.py), fallback request.client.host; ua = header[:200] hoặc '' — stored in request_logs ip/ua columns.

### Web
- sonner: `<Toaster/>` mounted in App; theme follows dark default.
- Toasts on ALL mutations: login/logout, upload (success: "Đã tải lên #{id} — đang chờ xử lý" + navigate /jobs; error: detail), region save, result save, export (create/pdf/download/delete), admin status/role, password/email change, wizard errors (upload failures surface toast too).
- ApiError: `TypeError: fetch failed` class → message "Không kết nối được máy chủ. Kiểm tra server đang chạy." (deterministic mapping, unit-tested).
- ImageCropWizard: canvas-only render (hide `<img>`; canvas sized from natural image); no-rect submit → uploadJob(original File) with toast "Không có vùng chọn — gửi ảnh gốc"; icon toolbar above canvas (RotateCw, Eraser/X, Send icons from lucide-react) each with `title` tooltip; existing testids preserved/adjusted (R51).

### Admin
- Users page + Audit page layout per ui-ux skill: table spacing/typography tokens, role badges, action icon-buttons, sticky header; audit table shows IP + UA columns (truncate w/ title).
- Server audit endpoint response includes ip/user_agent fields.

## Non-goals
Stats dashboards; realtime queue processing; Alembic; PDF iframe sandboxing change; mammoth staleness.
