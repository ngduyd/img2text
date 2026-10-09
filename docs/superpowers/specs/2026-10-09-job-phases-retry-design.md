# Spec: Job status phases + per-step retry + restart-proof kernel tracking

Date: 2026-10-09
Status: approved approach A (user: "A")
Path: architectural (brainstorming → spec → plan → SDD execution)

## Problem

1. **Bug**: job 3 kẹt `running` vĩnh viễn. `_batch_runs` in-memory
   (`kaggle_orchestrator.py:67`) → server restart mất kernel ref → poll loop
   không còn → kernel Kaggle xong nhưng backend không ingest, `result=NULL`.
2. **UI thiếu granularity**: một status `running` che cả 2 phase (OCR + layout
   build) → retry không biết chạy lại bước nào.
3. **Label lỗi thời**: "Đang chờ worker Colab" (`web/src/lib/status.ts:6`).
4. **Retry thiếu vị trí**: nút thử lại chưa có ở các state/step.

## Intent (user request)

- Sửa bug job 3.
- Đổi nhãn `queued` → **"Đang lập lịch"**.
- Tách `running` → **`extracting`** ("Đang trích xuất văn bản") +
  **`rendering`** ("Đang dựng layout").
- Retry đúng bước: fail ở bước nào → retry chạy lại bước đó.
- Nút "Thử lại" ở mọi vị trí thiếu.

## Design (approach A — status thật)

### Status machine

```
queued (Đang lập lịch)
  → extracting (Đang trích xuất văn bản)   [kernel pushed / HTTP worker claim]
  → rendering  (Đang dựng layout)           [ingest OK: result stored]
  → done                                  [auto-gen layout xong]
failed                                   [mọi step]
```

- `jobs.status` TEXT — không cần migration enum, chỉ đổi transition code.
- Mới: `jobs.kaggle_ref TEXT` — persist kernel ref (restart recovery).
- Mới: `jobs.failed_step TEXT` NULL | `extracting` | `rendering` — retry target.

### Transition points (server)

| Event | Trước | Sau |
|---|---|---|
| tạo job / requeue | queued | queued |
| spawn batch push OK (`kaggle_orchestrator.py:447`) | running | **extracting** (+ ghi `kaggle_ref`) |
| HTTP worker claim | running | **extracting** |
| ingest OK (`_ingest_batch_result` → `_store`) | running | **rendering**, rồi auto-gen → **done** |
| kernel failed/error/cancelled/timeout (`_FAILED_STATUSES`) | — | **failed** + `failed_step=extracting` |
| auto-gen layout: cả md + docx fail | — | **failed** + `failed_step=rendering` |
| auto-gen: 1 trong 2 OK | — | **done** (warning log, như hiện tại) |
| proofread fail | không đổi status (fire-and-forget, warning) | — |

### Restart recovery (bug job 3)

- `_spawn_batch_run` ghi `kaggle_ref` vào DB.
- `_ensure_batch_runs` mỗi tick: job `extracting` có `kaggle_ref` chưa có trong
  `_batch_runs` → **adopt** (re-add map → poll resume → ingest chạy tiếp).
- Job `extracting` mà KHÔNG có `kaggle_ref` (spawn nửa chừng) → reaper requeue
  về `queued`.
- Reaper hiện revert `running` → `queued` (`jobs_requeue.py:24`,
  orchestrator:488) → đổi WHERE sang `extracting`.

### Retry (unified)

- `POST /api/jobs/{id}/retry` — chỉ job `failed` (khác → 409):
  - `failed_step=extracting` → reset `queued` (spawn lại kernel).
  - `failed_step=rendering` → giữ `failed` → chạy lại `auto_generate_output`
    → success → `done`.
- Giữ `retry-layout` hiện có (ExportBar dùng cho layout cache miss) — không đổi.
- Hoàn tất rút gọn endpoint: `retry-layout` vẫn là-is (backward compat).

### Cleanup tập tin cũ

- `_show_ir.py`, `_ir_sample.md`, `_ir1.json` (scratch, untracked) → xóa
  (được user phê duyệt trong plan execution).

### Web

- `web/src/lib/status.ts`: label map
  - `queued: "Đang lập lịch"`
  - `extracting: "Đang trích xuất văn bản"`
  - `rendering: "Đang dựng layout"`
  - done/failed giữ nguyên.
- `JobStatus` type (`api/types.ts:47`) + `StatusFilterTabs` options + stats
  counts → thêm 2 status.
- Chip color/visual theo DESIGN.md tokens (extracting ≠ rendering, radius 6/8).
- **Retry buttons** (testid pattern `btn-retry*`):
  - `JobRow` khi failed → gọi `/retry` (hiện chưa có).
  - `JobDetail` status area khi failed.
  - `UnifiedEditor` layout-cache miss → `btn-retry-layout` (đã có, giữ).
- R59: mọi mutation → toast.

## Error handling

- Retry endpoint: 409 khi không phải failed; 404 job không tồn tại;
  authz như các endpoint jobs khác.
- Poll adopt fail (kernels_status lỗi) → warning, giữ nguyên, tick sau thử lại.
- Không nuốt exception mới nào (R-quality bar giữ nguyên).

## Testing

Server (TDD, red → green):
- spawn ghi `kaggle_ref` + status=`extracting`.
- restart simulate: `_batch_runs` trống + job `extracting` + ref → adopt →
  ingest chạy.
- kernel `cancelled` → `failed` + `failed_step=extracting`.
- ingest OK → `rendering` → auto-gen OK → `done`.
- auto-gen cả 2 fail → `failed` + `failed_step=rendering`.
- `POST /retry`: extracting-step → queued; rendering-step → re-run → done;
  409 khi không failed.
- Reaper revert `extracting` → queued.

Web (vitest):
- status label map mới (5 status).
- JobRow retry button visible khi failed → click → toast + refetch.
- JobDetail retry.
- StatusFilterTabs 5 options, stats counts.
- JobStatus union type mở rộng → tsc xanh.

## Migration / deploy

- `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kaggle_ref TEXT;`
- `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_step TEXT;`
- Dev DB + test DB apply trước khi test.

## Out of scope

- Proofread retry riêng (fire-and-forget, giữ nguyên).
- Stats dashboard, Alembic, worker token lifecycle.
