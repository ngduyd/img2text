# Plan K5 — Backend ↔ Kaggle batch integration (spec)

User: "Ghép lại với backend" sau khi batch flow chạy通 (kernel complete 320s, output pulled). Mô hình: backend tự làm client — queued job → stage input (lấy file từ storage) → dataset img2text-input → push kernel batch → poll (status normalize) → kernels_output → parse result.json → ingest vào job (done + result payload). KHÔNG cần public URL (vượt blocker production trước đó). K2 loop-kernel (poll backend, cần public URL) giữ lại sau cờ `kaggle_mode=loop`.

## Design
1. Config: `kaggle_mode` (env KAGGLE_MODE, mặc định "batch", values batch|loop) — batch = mặc định mới. Các kaggle_* giữ nguyên (đã có: username/key-or-token/kernel_ref/accelerator/min_queue/min_gap/stage_src/stage_dir).
2. `services/kaggle_orchestrator.py` mở rộng:
   - `ensure_worker()` mode dispatch: mode=loop → nhánh K2 cũ (unchanged); mode=batch → `_ensure_batch_runs()`.
   - `_ensure_batch_runs()`: map in-memory `{job_id: kernel_ref}` (module-level); với mỗi job status="queued" (limit: tối đa 1 spawn mới mỗi tick — chống burst): nếu job đã có ref đang poll → skip; gap guard; → `_run_batch_for_job(job)`:
     a. storage.get(job.storage_key) bytes → stage input file (tên theo ext) vào /tmp stage input + dataset metadata (id owner/img2text-input) → nếu dataset tồn tại: DELETE rồi CREATE (đúng pattern run_one/K3 đã verify trên API thật) — ceiling: slug dùng chung, 1 job/lần spawn (đồng thời = đè nhau — sequential per tick nên OK).
     b. stage kernel (script img2text_batch.py + kernel-batch-metadata dataset_sources chỉ img2text-input) từ deploy/kaggle (compose mount /app/deploy/kaggle:ro đã có) → kcompat kernels_push.
     c. map[job_id] = ref; lần tick sau: poll normalized status: complete → `_ingest_batch_result(job, output)`; failed/error → log warning + xóa ref (job vẫn queued → tick sau spawn lại; gap guard chống loop tight).
   - `_ingest_batch_result`: kernels_output(ref, fresh tmp dir) → đọc result.json → ADAPTER blocks→ResultBody: pages[] = mỗi trang: {index (theo trang trong input — batch OCR cả file → index = thứ tự trang ĐẦY ĐỦ 1..N; preprocess ceiling: nếu job.preprocess có pages/rotate → log warning "kaggle batch bỏ qua preprocess (sử dụng worker loop/K2 cho preprocess)" + ingest toàn bộ), width/height từ result.json (nếu script ghi — K4 script ghi pages có image path; width/height KHÔNG có → adapter lấy từ result.json nếu có else 0), regions[] = blocks: {id, bbox:[x1,y1,x2,y2], type: block.type, text: block.text, confidence: null}, markdown = builder: doc_title→"# ", paragraph_title→"## ", text→text thường, table→HTML table (block.text đã là HTML theo notebook), image→bỏ qua (batch-grade, đã document), ngắt trang "---"; markdown chung = join các trang. gpu_seconds = 0 + comment ceiling (kernel log elapsed = wall, không tách GPU).
   - Ingest qua lại dùng schemas.ResultBody validation + code path result endpoint hiện có — TÁCH service function từ routers/jobs.py result handler (nhỏ: nhận job_id + body + session) để cả HTTP worker protocol lẫn orchestrator dùng chung; result handler gọi lại (không đổi behavior, test hiện có giữ nguyên).
   - Timeout mỗi batch run: settings.kaggle_timeout (đã có, 10800) — ref quá hạn → xóa ref + warning (spawn lại sau).
3. Scheduler: giữ nguyên wiring (ensure_worker đã gọi theo interval) — dispatch theo mode bên trong.
4. Compose/env: thêm KAGGLE_MODE vào passthrough + .env examples. README: cập nhật mục Kaggle — batch = mặc định, không cần public URL; loop = production khi có URL (K2).
5. Tests (mock kaggle + storage + DB, test DB :5436):
   - batch flow happy: queued job → stage input (storage.get called với uploads/ key) → delete+create dataset → kernels_push (stage chứa img2text_batch.py + metadata dataset_sources [img2text-input]) → tick sau status complete (format enum thật) → kernels_output → job status=done + result payload: pages count đúng, regions từ blocks, markdown builder (doc_title→"# "), confidence null.
   - preprocess ceiling: job.preprocess set → warning logged + vẫn ingest toàn bộ.
   - failed status → ref xóa, job còn queued, tick sau spawn lại (gap guard respect).
   - timeout ref → xóa + warning.
   - mode=loop → nhánh K2 cũ không đụng (test dispatch).
   - adapter unit: blocks→ResultBody (table HTML giữ, image bỏ, empty text bỏ).
   - existing tests giữ nguyên (result endpoint refactor — chỉ move, không đổi).
6. Gates: server full suite nohup (~10-11 phút, DATABASE_URL :5436) → 165+ green; deploy/kaggle tests giữ 52.

## Non-goals
Public URL/loop mode thay thế; preprocess cho batch (ceiling có log); parallel batch jobs (1/tick); column DB theo dõi kernel (in-memory map, restart = orphan kernel ceiling có docstring).
