# Spec: Wave-2 — xóa job, báo done, jobs list, preprocess batch, quota thật, heartbeat, IR viewer, PDF font

Nguồn: user list10 vấn đề (2026-10-14) + phân tích xác minh code. Wave này TIẾP sau
jobdetail-redesign (merge xong) + fix-render-llm. #5 (unify batch output) + #10 (Redis rate-limit)
ngoài scope — cần spec riêng / sau MVP.

## P0 (demo-blocker)

### #2 Báo job xong (web)
- JobDetail + Jobs: theo dõi transition pending→done/failed trong polling (React Query
  `statusUpdate`) → `toast.success("Job #X đã xong")` / `toast.error("Job #X thất bại: …")`.
- Browser Notification API: lần đầu done → xin permission 1 lần; nếu granted → notify
  (title "img2text", body tên job). Không mail/webhook/SSE (defer, YAGNI MVP).
- Test đỏ-xanh: rerender job mock pending→done → toast gọi; failed → toast lỗi.

### #9 PDF export tiếng Việt không rớt dấu
- Dockerfile (server): đảm bảo `fonts-dejavu` (extra bold/italic) + fontconfig present.
- Smoke test: render markdown có dấu + song ngữ qua export pdf path → bytes > 0;
  assert embedded fonts (pypdf: `/Font` dict non-empty, tên font DejaVu) — chặn file
  "mở được nhưng rỗng dấu".
- WeasyPrint config: `@font-face`/font-family explicit trong CSS template xuất pdf.

### #6 Quota chống khai láo page_count (server, retro-correct)
- Ingest (batch + loop): cập nhật `job.page_count` = số trang THẬT từ OCR result
  (`len(result["pages"])`). Quota SUM phản ánh thật ngay job đầu tiên.
- Test: create khai 1 trang → ingest trả 3 pages → job.page_count=3 → quota me dùng 3.

## P1

### #1 DELETE job (server + web)
- `DELETE /api/jobs/{id}` → 204: chỉ owner (hoặc admin); job đang `extracting/queued/rendering` →
  cho xóa (ingest guard: job missing → discard + warn, đã có pattern cancel);
  storage cleanup prefix `exports/{id}/` (gồm crops), versions rows, input object R2 key;
  xóa row. Quota tự phản ánh (SUM realtime).
- GDPR: endpoint = xóa toàn bộ data cá nhân của job (input + derived).
- Web: nút "Xóa" (destructive, confirm dialog useDialogA11y, toast R59) ở JobRow overflow +
  JobDetail menu. R51 giữ testids.
- Test: delete done → storage prefix gone + row gone + 404 sau; delete job khác user → 403.

### #4 Kernel batch đọc preprocess (deploy/kaggle)
- `img2text_batch.py` fetch_manifest_jobs đọc key `preprocess` (server đã gửi từ P2-6) →
  `_apply_preprocess` (reuse pattern Colab loop): page-select + rotate trước OCR.
- Test: manifest có preprocess={"pages":[1,3],"rotate":90} → mock pipeline nhận preprocess.

### #3 Jobs list search + sort server-side (server + web)
- `GET /jobs` thêm params: `q` (ILIKE filename), `sort= newest|oldest` (default newest),
  `status` (đẩy filter tabs lên server thay vì client-only trên trang).
- Web: ô search debounced 300ms (testid `jobs-search`), sort select; StatusFilterTabs
  gọi param server; pagination giữ nguyên (R55 page numbers).

### #7 Worker heartbeat (server + admin web)
- Migration: `CREATE TABLE worker_heartbeats (worker_id text PRIMARY KEY, kind text,
  last_seen timestamptz, current_job_id int null);`
- Colab loop poll `/next` + heartbeat endpoint `POST /api/worker/heartbeat` (token auth
  worker_token pattern) → upsert last_seen/current_job_id; batch marker: orchestrator
  upsert row kind="kaggle-batch" khi spawn + last_seen khi poll status.
- `GET /api/admin/workers` → rows + derived (silent_seconds, job, lease_remaining).
- Admin card "Workers": last_seen, job đang giữ, badge im lặng > 2 lease (amber);
  queue_depth hiện tại + cảnh báo log khi depth > N quá M phút (scheduler check nhẹ).
- Test: heartbeat upsert; workers endpoint admin-only; silent > 2 lease → flag.

### #8 IR viewer UI (web)
- JobDetail InfoPanel (hoặc section debug): collapsible "IR (JSON)" → fetch
  `GET /jobs/{id}/ir` → pretty JSON `<pre>` (testid `ir-viewer`), copy button.
- Test: mở panel → hiển thị document_id; 404/409 (chưa render) → ẩn nút.

## P2 / Ghi nhận
- #5 unify batch output schema (full regions như loop) — SPEC RIÊNG, cần session design.
- #10 rate-limit Redis — sau MVP.
- Stats wave (UTC→local, gpu failed, page_views filter, usd rate) — lane riêng đã bàn.
- worker_token hash (R11) — vẫn lỡ hẹn.

## Migration checklist (thêm)
- CREATE TABLE worker_heartbeats (...);

## Phasing
- Lane E (web): #2 toast, #8 IR viewer, #3 web, #7 admin card
- Lane F (server): #1 DELETE, #6 quota ingest, #9 font+test, #4 kernel, #3 API, #7 server
- Launch SAU khi jobdetail-redesign + fix-render-llm merge (tránh conflict JobDetail/render).

## Testing
- Server: delete cascade (storage mock), quota ingest-correct, heartbeat upsert,
  /jobs q/sort/status, PDF font smoke, manifest preprocess.
- Web: toast transition, IR viewer, search debounce + sort, delete confirm flow,
  admin workers card.
