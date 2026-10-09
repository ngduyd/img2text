# Spec: Redesign UI soạn thảo + version hóa tài liệu

Date: 2026-10-10
Status: design đã duyệt qua brainstorming (upload, list, detail, trang trích xuất, sync algorithm, version history)
Path: architectural → spec → writing-plans (phân phase)

## Problem

- Editor sửa trực tiếp artifact layout (md-layout / docx.html) → md và docx lệch từ khi sửa (2 nguồn sự thật).
- Không có version history / undo; sửa nhầm khó hồi phục.
- Layout LLM thỉnh thoảng render rỗng (đã fix ở mức tối thiểu) nhưng chưa có luồng "sửa text gốc → đồng bộ layout" tiết kiệm LLM.
- UI thiếu: phân trang, bulk retry, mode tạo job, split-view; thừa component (badge "Đầu ra: Word", stats vùng, cụm nút tải rời).

## Intent

- **1 nguồn sự thật = text gốc (extraction)**; layout là downstream, sửa text gốc rồi đồng bộ (incremental, không gọi LLM khi có thể).
- Job detail vẫn cho sửa layout trực tiếp (fine-tuning), nhưng có **phát hiện stale/conflict + version history/undo** để không mất dữ liệu.
- Trang trích xuất văn bản: xem text gốc + lỗi bôi vàng + click-fix; không phải editor tự do.
- UI gọn: Jobs list pagination + bulk retry; upload mode selector; gỡ component thừa; gộp nút tải.

## Quyết định đã chốt (từ brainstorming)

- Sync incremental: **lưu text = bắt đầu đồng bộ**; endpoint chỉ return khi cả 2 artifact persist xong → UI mới hiện "xong".
- Version: **(b)** — history + undo (giữ N snapshot), cộng stale/conflict detection.
- Cả 2 surface sửa được (job detail = layout; trang trích xuất = text gốc).
- Mode tạo job: "Lấy layout" (OCR + dựng md/docx) vs "Chỉ trich xuất văn bản" (OCR thôi).
- Render: giữ LLM render; LLM fail/echo → fallback heuristic (render thủ công).

## Non-goals

- Back-sync layout→text (lossy, tránh).
- Đổi pipeline OCR/Kaggle batch.
- Realtime collaborative editing.

---

## Sub-system A: Version storage + sync + conflict (NỀN TẢNG — Phase 1)

### Data model

Bảng mới `document_versions`:

```
id            bigint PK
job_id        bigint FK → jobs
kind          text  -- 'text' | 'md-layout' | 'docx-layout'
storage_key   text  -- S3 object của snapshot
version       int   -- tăng dần per (job, kind)
based_on_text_version int  -- text_version mà artifact này render/sync từ (kind=text thì = version của chính nó)
detached      bool  -- layout bị sửa trực tiếp (không còn track text)
created_at    timestamptz
```

`jobs` thêm cột (hoặc derived): `text_version int` (bump mỗi lần lưu text gốc).

Snapshot = object S3 (reuse storage layer), N = 20 gần nhất per (job, kind), prune auto.

### Sync algorithm (incremental, 0 LLM)

Khi lưu text gốc (accept suggestion hoặc edit):
1. Persist text gốc (S3) + bump `text_version` + tạo version row kind=text.
2. Với mỗi layout (md-layout, docx-layout) CHƯA detached:
   - **md-layout**: find `old_phrase → new_phrase` (text thuần) trong artifact; thay đúng occurrence (theo suggestion offsets hoặc count).
   - **docx-layout** (docx.html): parse HTML → walk text nodes → replace trong text node (giữ tags).
   - Persist artifact mới (S3) + version row (based_on_text_version = text_version mới).
3. **Atomic per-layout**: nếu 1 layout targeted-fail (phrase không thấy, cắt node) → layout đó KHÔNG update → trả "cần render lại" cho layout đó (không để partial).
4. Endpoint **chỉ return sau khi persist xong** (blocking request, incremental nhanh). UI chỉ flip state khi 200.

### Conflict / staleness

- Layout `based_on_text_version < text_version` → **stale** → UI badge "cần đồng bộ" + nút sync.
- Layout **detached** (edit trực tiếp) → sync-from-text KHÔNG tự ghi đè → API trả conflict → UI warn "Layout có chỉnh tay. Đồng bộ sẽ ghi đè. Tiếp tục?" → user confirm → ghi đè (version history đã có backup để undo).
- Optimistic lock: save dùng `text_version` expected → nếu 2 edit đua → 409 → refresh.

### API (Phase 1)

- `POST /api/jobs/{id}/extraction` — save text gốc + sync incremental → 200 (đã sync) | 200 `{"needs_render": ["md-layout"]}` | 409 conflict.
- `GET /api/jobs/{id}/extraction` — text gốc + version.
- `GET /api/jobs/{id}/versions?kind=` — list version rows.
- `POST /api/jobs/{id}/versions/{vid}/restore` — undo (restore snapshot → version mới).
- `POST /api/jobs/{id}/render-layout` — full LLM re-render (tách từ retry-layout, set detached=false, based_on_text_version=text_version).

---

## Sub-system B: Trang trích xuất văn bản (Phase 2)

- Route `/jobs/:id/extraction`. Render text gốc (HTML per trang/region).
- Từ detect sai (từ proofread suggestions) → **highlight vàng** (`bg-warning/20` + underline dotted).
- Click highlight → **popover** gợi ý (phrase → suggestion + reason + Áp dụng/Bỏ qua) — KHÔNG modal.
- Áp dụng → gọi `POST /extraction` (save+sync) → UI loading → 200 → hiện layout mới (invalidate) hoặc "cần render lại" → nút "Vẽ lại layout".
- Nút **"Vẽ lại layout"** (primary accent) → full LLM render (async, có progress).
- Link qua lại extraction ↔ job detail.
- R59 toast; loading skeleton; contrast ≥4.5; no em-dash.

## Sub-system C: Job detail split-view + gỡ component (Phase 3)

- Split-view: trái = **bản có layout** (sửa được: MDEditor/Tiptap như hiện tại) | phải = **bản gốc** (ảnh/OCR text để đối chiếu). Tỷ lệ: trái rộng (7/12) + phải hẹp (5/12) — override nếu bạn muốn 50/50.
- **Gỡ**: badge "Đầu ra: Word"; statsLine "Tổng 21 vùng · ..."; component 2 nút tải rời.
- **Gộp nút tải**: 1 cụm duy nhất trong rail (`ExportBar` giữ, bỏ card bọc ngoài thừa).
- Sửa layout trực tiếp → set `detached=true` + version row kind=layout.

## Sub-system D: Jobs list pagination + bulk retry (Phase 4)

- **Pagination server-side** (10/trang) — API `GET /jobs?page=&page_size=`.
- Checkbox mỗi hàng + "select all (trang này)".
- Bulk bar (sticky bottom) khi có chọn: "n đã chọn · [Chạy lại đã chọn]" → gọi retry cho các job failed được chọn.
- Giữ filter tabs.

## Sub-system E: Upload mode selector + cụm nút (Phase 5)

- Cụm [Hủy][Gửi lên · format ▾]移到 khung upload **góc trên bên phải**.
- Wizard thêm **mode**: "Lấy layout" (+ format md/docx) | "Chỉ trich xuất văn bản".
- `jobs.output_format` nullable + `mode` (extract_only | layout). extract_only → bỏ qua auto-gen layout.

---

## Error handling (chung)

- Sync/render fail → không bao giờ để artifact partial (atomic per-layout; transaction).
- UI không hiện layout stale làm current (badge stale).
- Optimistic-lock conflict → refresh + toast.
- LLM render fail/echo → fallback heuristic (đã có).
- Version prune fail → warning, không block save.

## Testing (TDD, per phase)

- **A**: sync incremental replace (md + docx.html text-node), atomic fail, stale detection, conflict detached, optimistic lock 409, version prune, restore.
- **B**: highlight render, popover accept → POST → UI update, "cần render lại" path.
- **C**: split-view render, gỡ component (không còn badge/stats), detach flag khi edit layout.
- **D**: pagination API + UI, bulk retry selected, filter interaction.
- **E**: mode selector → job.mode, extract_only bỏ auto-gen.

## Migration / deploy

```sql
CREATE TABLE document_versions (...);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS text_version int DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mode text DEFAULT 'layout';
```
Dev + test DB apply trước khi test.

## Phasing (thực thi)

- **Phase 1 (nền tảng)**: Sub-system A (version storage + sync + conflict + API). Mọi phase sau phụ thuộc.
- **Phase 2**: trang trích xuất (B) — dùng API Phase 1.
- **Phase 3**: job detail split-view + gỡ component (C).
- **Phase 4**: jobs pagination + bulk retry (D).
- **Phase 5**: upload mode selector + cụm nút (E).

Mỗi phase = 1 plan + review loop + merge, như pipeline hiện tại.

## Câu hỏi mở (cần user trước khi implement)

1. Split-view tỷ lệ: 7/5 (layout rộng) hay 50/50?
2. Bulk retry: chạy lại OCR (extracting) hay cả layout? (default: chạy lại toàn bộ job như retry hiện tại)
3. Sync incremental mặc định tự động khi accept, hay cần bấm "Đồng bộ layout"? (trước nói lưu text = bắt đầu đồng bộ → auto. confirm.)
