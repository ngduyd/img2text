# Spec: Kaggle batch one-run (N jobs / 1 kernel run)

Date: 2026-10-09
Status: approach A approved (user: "A")
Path: architectural (brainstorming → spec → writing-plans → SDD)

## Problem

`_ensure_batch_runs` spawn tối đa 1 run/1 job, chặn toàn bộ khi còn run
tracked (shared dataset slug). Kernel `find_input()` nhận 1 file. N job xếp
hàng = N kernel run = N × setup (unpack env 1.6GB + Paddle init ~2-3 phút).
Chi phí setup nhân với N.

## Intent

Một kernel run xử lý TOÀN BỘ job queued. Setup trả 1 lần cho cả lô. Phân
ảnh thất bại: 1 job fail không chặn các job còn lại.

## Design

### Staging (server)

- `_spawn_batch_run` nhận **danh sách jobs** (tất cả `queued`, cap
  `settings.kaggle_batch_max_jobs`, default 20, env
  `KAGGLE_BATCH_MAX_JOBS`).
- Mỗi job copy file vào staging dataset với tên `{job_id}__{orig_name}`
  (job_id prefix = mapping ngược không mơ hồ).
- **Verify-before-push** (giữ anti-stale af01d94): `dataset_list_files`
  phải chứa ĐỦ mọi filename đã stage → mới `kernels_push`. Thiếu → skip
  spawn + retry tick sau (không push vào dataset cũ).
- Dataset slug vẫn `jhandf/img2text-input` (shared, không đổi).

### Kernel (deploy/kaggle/kernel/img2text_batch.py)

- `find_input()` → `find_inputs()`: glob `/kaggle/input/**/*`, filter
  file thường, **sorted**, trả list (job_id parse từ prefix `{id}__`).
- Loop mỗi input: pages → OCR → ghi output **per job**:
  `{job_id}_result.json` (+ md nếu pipeline đang ghi) vào
  `/kaggle/working` (script-kernel capture).
- 1 input fail (exception/OCR crash) → log + **tiếp tục input kế** (không
  SystemExit giữa lô); cuối run exit 0 miễn ≥1 output ghi được; 0 output →
  exit 1.

### Orchestrator (server/app/services/kaggle_orchestrator.py)

- `_batch_runs` đổi shape: key = **ref** (run-level):
  `{"ref", "pushed_at", "job_ids": [int]}`. `_batch_runs` = dict[str, dict].
- Spawn: UPDATE TẤT CẢ job trong lô → `extracting` + `kaggle_ref=ref`
  (1 transaction); ref sinh 1 lần cho run.
- Poll (mỗi tick, mỗi ref 1 lần):
  - kernel `success` → ingest per job: pull `{job_id}_result.json`. Job có
    output → `_store` (→ rendering,auto-gen…). Job **thiếu output** →
    `failed` + `failed_step=extracting` + `error="kernel thiếu output"`,
    các job khác vẫn ingest bình thường (partial-fail policy).
  - kernel `failed`/`error`/`cancelled`/`timeout` → MỌI job trong run →
    `failed` + `failed_step=extracting` + `error=f"Kaggle kernel {status}"`.
  - `kaggle_timeout` → mọi job trong run → revert `queued` (giữ hành vi
    hiện tại, mở rộng cho lô).
- **Adopt/restart**: SELECT jobs `extracting` + `kaggle_ref IS NOT NULL` +
  `worker_token IS NULL` → **group theo ref** → mỗi ref 1 entry
  `{ref, pushed_at=now, job_ids=[...]}`. Job cùng ref không còn map →
  adopt. Ref có ≥1 job live → coi như run active (không spawn đè).
- Single-active-run guard giữ nguyên (shared slug): chỉ spawn khi
  `_batch_runs` rỗng + min_gap.
- In-memory chỉ còn key theo ref; không còn per-job key.

### Config

- `kaggle_batch_max_jobs: int = 20` (env `KAGGLE_BATCH_MAX_JOBS`).

### Không đổi

- Status machine (extracting/rendering/done/failed + failed_step).
- Web UI, API contracts, `kaggle_ref`/`failed_step` columns.
- Verify-before-push semantic (chỉ mở rộng: ĐỦ file của lô).
- HTTP worker mode.

## Error handling / partial-fail policy

- Job riêng lẻ fail trong lô → isolated; lô vẫn chạy.
- Output rỗng/không parse được cho 1 job → job đó failed+extracting
  (error cụ thể), không ảnh hưởng job khác.
- Staging/verify fail → không spawn, tick sau thử lại (như hiện tại).

## Testing (TDD)

Server (orchestrator tests, `img2text_test`):
- spawn stage N file `{id}__{name}` + verify đủ → push 1 ref + N job
  extracting cùng ref.
- verify thiếu 1 file → không push, không mark extracting.
- poll success + đủ N output → N job rendering (ingest).
- poll success + thiếu output job 2 → job1/3 rendering, job2 failed
  + failed_step=extracting + error.
- poll cancelled → N job failed + failed_step=extracting + error.
- kaggle_timeout → N job queued.
- adopt: 2 job cùng ref, map trống → 1 run entry chứa cả 2; ref live →
  không spawn mới.
- cap: queue > max → spawn max, phần còn lại chờ tick sau.

Kernel: unit-level test parse `find_inputs` (job_id prefix, sorted, skip
dir) — import được module (kaggle-only imports guard).

## Migration / deploy

- Không migration DB.
- Deploy: push kernel mới (`kernel-metadata.json` không đổi) + server env
  thêm `KAGGLE_BATCH_MAX_JOBS` (optional).

## Out of scope

- Streaming ingest từng job trong lúc kernel đang chạy (chỉ ingest sau
  run success).
- Priority queue / job weighting.
- Đổi tên dataset slug hay per-run dataset.
