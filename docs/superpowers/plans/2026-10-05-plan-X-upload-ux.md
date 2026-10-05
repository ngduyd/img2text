# Plan X — Upload UX + Reliability

Spec: docs/superpowers/specs/2026-10-05-plan-X-upload-ux-design.md (decisions R58–R62).
Worktree: .worktrees/plan-ux branch plan-ux. Baseline master @ cf919af.
All test commands per lane README-dev conventions (server: no prefix; web: npm test + tsc + build; worker untouched this plan).

## Task 1 — Server: CORS + interval env + upload claim kick
1. server/app/core/config.py: add `allowed_origins: str` env ALLOWED_ORIGINS (comma-sep regex, default "http://localhost:.*|http://127\.0\.0\.1:.*|.*vscode\.dev") + `scheduler_interval_seconds: int` env SCHEDULER_INTERVAL_SECONDS default 60 floor 5.
2. server/app/main.py: app.add_middleware CORSMiddleware allow_origins=re.compile("|".join(allowed)), allow_credentials=True, allow_methods/headers default safe set. Comment: prod nginx same-origin; regex covers vscode forward origins.
3. server/app/main.py: existing lifespan loop already references settings.scheduler_interval_seconds — verify it uses the new field (replace hardcoded 60 default if present).
4. server/app/routers/jobs.py create_job: after commit, spawn background task `asyncio.create_task(_kick_processing(settings))` where _kick_processing acquires scheduler._claim_lock and runs one `_run_jobs_once` claim attempt under try/except (log warning on failure). Response unchanged 201. Test: POST /jobs with scheduler faked (monkeypatch scheduler._run_jobs_once async mock) → after response, mock awaited once; storage put happened; failure path (mock raises) → response still 201, log warning.
5. Tests: CORS preflight+GET from allowed origin (vscode.dev pattern) → access-control-allow-origin header present; disallowed origin → absent; interval env floor; kick called once on create (happy + failure).
- TDD red→green; commit "feat(server): cors middleware, admin interval env, upload claim kick".

## Task 2 — Web: sonner toasts + network-error mapping
1. web: npm i sonner. App.tsx: import { Toaster } from "sonner"; mount <Toaster theme={dark? "dark":"system"} position="top-right" richColors /> (match token palette).
2. web/src/lib/errors.ts: mapApiError(e) — ApiError → e.detail; TypeError/fetch-failed → "Không kết nối được máy chủ. Kiểm kiểm tra server đang chạy." Unit-test both branches.
3. Wire toast.success/error via mapApiError into EVERY mutation hook (useLogin, useLogout, useUploadJob [success = "Đã tải lên — đang chờ xử lý" + navigate("/jobs")], useUpdateResult, useUpdateRegion, useExportJob, useCreateExport, useDeleteExport, useUpdateUserStatus, useUpdateUserRole, useChangePassword, useChangeEmail) + Dropzone upload error inline retained + WizardErrors via toast on submit failure.
4. Tests: existing hooks tests gain toast assertions where cheap (mock sonner: toast.success called with mapped detail on error; upload success navigates /jobs). New client test for mapApiError TypeError branch.
- TDD; commit "feat(web): sonner toasts across mutations + network-error mapping".

## Task 3 — Web: ImageCropWizard fixes
1. Remove visible <img> (keep for natural-dims measurement offscreen); canvas = sole render surface; draw image into canvas at natural dims (or capped display scale w/ pixel coords preserved).
2. No-rect on submit → api.uploadJob(file) original File + toast "Không có vùng chọn — gửi ảnh gốc" + onUploaded; REMOVE wizard-error path for empty rect.
3. Toolbar ABOVE canvas: lucide-react icons RotateCw (btn-crop-rotate, title "Xoay 90°"), Eraser (btn-crop-reset, title "Xóa vùng chọn"), Send (wizard-submit, title "Gửi lên", loading). Keep all existing testids (R51) + add data-testid unchanged names.
4. Tests: adjust existing (no rect → uploadJob(file) not error; toolbar above canvas assert order; single render assert canvas present, img.hidden or absent; icon buttons have title attrs).
- TDD; commit "fix(web): crop wizard single-canvas, default full image, icon toolbar".

## Task 4 — Audit IP/UA + admin UI redo (ui-ux skill)
1. Server: audit_entry writes in jobs.py + auth.py capture ip = X-Forwarded-For split(",")[0].strip() else request.client.host; user_agent = request.headers.get("user-agent","")[:200]; store in entry payload dict (metadata field). GET /audit list already returns payload — verify fields visible in response. Tests: seeded request with XFF+UA → entry payload contains them; missing → host, "".
2. Web admin (apply ui-ux-dev skill checklist — dark default, tokens, contrast, focus-visible, a11y, 320px): Users page — table layout tokens (spacing/typography), role badge, action icon buttons with title tooltips; Audit page — table w/ IP + User-Agent columns (truncate, title full), timestamp, actor. Keep all testids (R51).
3. Tests: audit API returns ip/user_agent fields; web Users/Audit tests still pass w/ adjusted queries only.
- TDD; commit "feat: audit ip/user-agent + admin ui redo".

## Task 5 — Gate + docs
1. Full suites: server ≥146 (137+new), web ≥134 (129+new), tsc, build. Fix root causes only.
2. README dev note: VSCode port-forwarding → CORS regex covers vscode.dev; ALLOWED_ORIGINS override for LAN access; SCHEDULER_INTERVAL_SECONDS documented in config table.
3. e2e-checklist: Section E — upload có toast thành công + nhảy /jobs; lỗi mạng hiển thị "Không kết nối được máy chủ"; wizard ảnh mặc định gửi ảnh gốc khi không chọn vùng; tooltip icon toolbar hiển thị tên tool; audit log có IP + User-Agent.
- Commit "chore: plan X gate + docs".

## Deferred minors ledger
- stats dashboard (explicit later); realtime queue processing (paid/production later); Alembic (separate plan); PDF iframe sandbox; mammoth staleness.

## Parallelization note
Sequential single-lane. server vs web disjoint but same worktree — no concurrent lanes.
