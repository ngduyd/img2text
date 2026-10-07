# Plan K2 — Backend tự điều phối Kaggle worker (spec)

Quyết định user: Kaggle = worker infrastructure; **backend tự điều phối** — server thấy queue job đầy/treo thì tự bắn run kernel Kaggle lên; kernel xử lý theo session rồi thoát; server tái kích khi cần. Manual push (Plan K) chỉ để khởi tạo kernel + Secrets ban đầu.

## Nghiên cứu chốt (đọc code thật)
- `worker/pipeline.py run_job`: vòng lặp poll `/api/jobs/next` FOREVER (204 → backoff 5-30s, không thoát khi rỗng) → session Kaggle (tối đa ~12h) tự chết → backend tái push run mới. Kernel KHÔNG cần đổi.
- Kaggle: `kernels push` = upload + run ngay; `kernels status(ref)` cho trạng thái run mới nhất; KHÔNG có lệnh run-only → tái kích = push lại (version mới). Accelerator `NvidiaTeslaT4`. Secrets (BASE_URL + RUNNER_KEY) đặt tay 1 lần trên kaggle.com (Plan K README).
- `server/app/services/scheduler.py`: interval job `reap_all` (SCHEDULER_INTERVAL_SECONDS) — hook point.

## Design
1. Config (core/config.py): `kaggle_username/kaggle_key` (env KAGGLE_USERNAME/KAGGLE_KEY — enabled khi cả 2 set), `kaggle_kernel_ref` (KAGGLE_KERNEL_REF, ví dụ "user/img2text-worker"), `kaggle_accelerator` (mặc định NvidiaTeslaT4), `kaggle_timeout` (10800), `kaggle_min_queue` (1 — spawn khi số job queued ≥ N), `kaggle_min_gap_seconds` (600 — chống spam spawn), `kaggle_stage_src` (nguồn files: mặc định deploy/kaggle/files + kernel metadata template).
2. Service `services/kaggle_orchestrator.py`:
   - `_api()`: lazy import `kaggle` (thiếu package → warning + disabled; KHÔNG crash server).
   - `_stage_kernel()`: build thư mục stage (mkdir -p, copy pipeline.py/verdict.py + dataset-metadata.json từ stage_src, sinh kernel-metadata.json với OWNER=username + kernel_ref + dataset_sources + accelerator + internet true) — idempotent, ghi vào `settings.kaggle_stage_dir` (/tmp).
   - `ensure_worker()` (sync, chạy trong to_thread): disabled → return; `kernels_status(ref)` == running/pending → return; đếm queued jobs trong DB (count status="queued") < min_queue → return; gap check (last_spawn in-memory) → return; `_stage_kernel()` + `api.kernels_push(stage_dir)` → log info; mọi exception → logger.warning (không crash). Trả về bool spawned.
3. Scheduler: trong `reap_all` (hoặc job interval riêng cùng trigger) gọi `await asyncio.to_thread(ensure_worker)` bọc try/except. Feature tự tắt khi không set env.
4. Compose dev: server service env passthrough KAGGLE_USERNAME/KAGGLE_KEY/KAGGLE_KERNEL_REF (default rỗng) + mount `./deploy/kaggle:/app/deploy/kaggle:ro` (đọc stage_src trong container). README: mục "Kaggle orchestration" (bật env, Secrets 1 lần, quota, BASE_URL public).
5. Tests `server/tests/test_kaggle_orchestrator.py` (mock sys.modules kaggle + DB fixtures): enabled+queued≥1+status complete → kernels_push gọi đúng 1 lần với stage dir; status running → skip; queued=0 → skip; thiếu env → không import; push raise → logged, ensure_worker trả False, không nổ; stage builder: OWNER + ref + accelerator substitution đúng, template không bị ghi đè; scheduler wiring: monkeypatch ensure_worker → reap job gọi. Chạy full suite.
6. Deploy production (note trong README, KHÔNG làm): server cần egress internet + Kaggle API creds trong env; kernel Secrets đã set 1 lần; production sync mechanism (user tự lo sau).

## Non-goals
Đổi worker/pipeline.py logic; auto-set Secrets;多user quota management; web UI cho orchestration.
