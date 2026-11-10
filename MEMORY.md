# MEMORY

## Now
- 2026-11-10 · **Đăng ký + OAuth Google**: (a) `AUTH_LIMIT` 10→**60/giờ/IP** + thêm chốt theo
  `(IP+email)` 10/15 phút (login, register, verify code, reset) — nguyên nhân 429 trong log là
  trần 10/giờ dùng chung sau nginx/NAT. (b) register: `smtp_host` rỗng hoặc `AUTO_VERIFY_EMAIL=true`
  → tự verify + bật `ocr_enabled` (trước đây tài khoản mới bị 403 `email_unverified` vĩnh viễn).
  (c) OAuth Google: `server/app/routers/oauth.py` (`/config`, `/google/start`, `/google/callback`),
  cột `users.oauth_provider|oauth_sub` + migration `2026-11-10_oauth.sql`, id_token xác thực qua
  `oauth2.googleapis.com/tokeninfo` (không tự parse JWT), liên kết theo email thay vì tạo trùng.
  (d) UI: trang đăng ký thiết kế lại (panel giới thiệu ≥lg, hint mật khẩu, toggle hiện/ẩn, bước
  nhập mã 6 số tại chỗ thay vì đẩy về "/" mở modal), nút Google ở cả /signin và /signup.
  Gate: pytest 1044, vitest 456, tsc sạch, build OK, `audit:a11y /signup,/signin` 0 findings
  (đã sửa 3 target <24px: toggle Hiện/Ẩn, link Quên mật khẩu, link Đăng ký).
- 2026-11-09 · **Phát hành v0.3.0**: tag `v0.3.0` (annotated) → `git push origin v0.3.0`.
  CD `42657553958` success: ci/server + ci/web + ci/worker + docker. Image đẩy lên DockerHub
  `img2text-server:v0.3.0|latest` và `img2text-web:v0.3.0|latest`. Quy trình phát hành từ giờ:
  push master → CI xanh → `git tag vX.Y.Z && git push origin vX.Y.Z` → CD tự build/push image.
- 2026-11-09 · **Push + CI**: đẩy 72 commit lên `origin/master` (`9bd698c..c0bdc7b`). CI lần 1
  (`42653086710`): web ✓, server ✓, **worker ✗** — `test_full_job_success_calls_heartbeat_per_page_and_result`
  `assert 0 == 1`. Nguyên nhân: test dùng `default_pdftoppm` mặc định → runner thiếu binary `pdftoppm`
  → FileNotFoundError → job fail sớm. Tái hiện: `env PATH=/tmp/nopop pytest` = cùng lỗi. Sửa: stub
  `rasterize_fn` trả PNG thật (PIL) — test này kiểm heartbeat/result, không kiểm rasterize.
  CI lần 2 (`42654575001`): **server + web + worker đều success**.
- Đo: worker suite 29 test = 11,5s (CI 11,6s), server 1031 = ~275s, vitest 456.
- CD (`.github/workflows/cd.yml`): chỉ chạy khi push tag `v*` (hoặc dispatch) → commit lên master
  KHÔNG chạy CD. Secrets `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` đã có, lần chạy v0.2.0 (Oct 23) success.
  Muốn phát hành bản demo: `git tag v0.3.0 && git push origin v0.3.0`.
- 2026-11-09 · **Chốt bản demo (B2–B5 + N1–N4, N7)** — đã sửa: default LLM = `role-scout`
  (`llm_model` + `proofread_llm_model`, model free cũ đã chết); proofread lỗi giờ ghi
  `jobs.proofread_error` + UI hiện "chưa kiểm được" thay vì "0 gợi ý"; `deploy/demo/seed.py`
  (1 user verified + 2 job `done` thật, 19 + 5 gợi ý) + `POST /api/jobs/sample` clone bản mẫu
  cho user mới + nút "Xem bản mẫu" ở empty state; `.env.dev.example` đủ 60 key (thiếu 0);
  README sửa bảng mode (batch = dev, session = prod); LICENSE MIT; `.gitignore` thêm `.agents/`
  + `!deploy/demo/*.jpg`; web/README ghi `SHOT_BASE`/`SHOT_EMAIL`.
- 2026-11-09 · Đo lại sau demo: server pytest **1031** (thêm 2 test proofread_error + 2 test
  /api/jobs/sample), web vitest **456**, tsc sạch, build OK, `audit:a11y` = `DONE 0 routes with
  findings`. Đo bằng Playwright trên vite preview: demo login thấy 2 job done + 19 highlight;
  user mới thấy empty state + nút bản mẫu → tạo job 113 mở đúng nội dung.
- 2026-11-09 · Còn mở (không chặn demo): UI mặc định **tiếng Anh** (spec S2) trong khi nội dung
  tiếng Việt — muốn đổi default `vi` thì sửa `web/src/i18n/index.tsx:12`. Dev DB còn 33 job
  `failed` rác (chỉ ảnh hưởng nếu demo bằng chính DB này — seed dùng tài khoản riêng nên sạch).
  B1 (đăng ký mới bị 403 `email_unverified` khi không có SMTP) chốt để cấu hình lúc deploy.
- 2026-11-09 · **Audit demo (CV intern/fresher)** — đo lại: server pytest 1027 ✓, web vitest 456 ✓,
  tsc ✓, build ✓, `audit:a11y` = `DONE 0 routes with findings` (8 route × 1440/320) ✓, export
  docx/pdf/md job 106 trả presigned URL thật ✓. Chặn demo: (1) đăng ký mới → 403 `email_unverified`
  vĩnh viễn vì không có SMTP; (2) default `LLM_MODEL`/`PROOFREAD_LLM_MODEL` là free model đã chết;
  (3) proofread lỗi trả 0 im lặng; (4) không có seed/demo data; (5) không GPU → job đứng `queued`.
  Lệch tài liệu: `.env.dev.example` thiếu 36/61 biến; README ghi batch deprecated trong khi dev dùng batch.
  `audit-a11y.mjs` cần `SHOT_BASE` + `SHOT_EMAIL` khi vite preview bind IP tailnet (không phải localhost).
- 2026-11-09 · **Spawn chỉ khi worker trước ĐÃ CHẾT**: trước khi spawn batch run, hỏi
  `kernels_status(ref)`; running/queued/pending → skip tick (log "chờ worker cũ chết").
  Lý do: `_batch_runs` là RAM → sau restart/crash giữa push và UPDATE DB, map rỗng dù kernel cũ
  vẫn chạy ⇒ có thể spawn 2 kernel tranh cùng dataset input. `kaggle_min_gap_seconds` hạ 600 → **120s**
  (runtime setting) vì điều kiện sống-chết giờ là chốt chính.
- 2026-11-09 · **Đo gom cụm 10 job / 1 kernel** (10 job × 4 trang bench4, `kaggle_batch_max_jobs=20`):
  push 06:21:20 → job cuối done 06:39:22 = **~18 phút cho 400 trang? Không: 40 trang** (10 job × 4) ⇒
  ~108s/job, ~27s/trang (đã chia sẻ setup ~7 phút). 1 job/kernel (job 93) = 478s ⇒ gom 10 job
  **nhanh hơn ~4,4×**; cả 10 job done, mỗi job 12 region (kết quả giống nhau, không rỗng).
  ⇒ Khi queue dài: gom job vào 1 run là tối ưu; muốn >20 job/run thì tăng `kaggle_batch_max_jobs`.
- 2026-11-09 · **Đo GPU thật** (file 4 trang nặng job 90, chạy qua orchestrator):
  tuần tự (job 93): 13+11+2+3 = **~29s OCR** (~7s/trang), wall 478s (setup ~7 phút);
  gộp lô 4 trang (job 96, batch_predict=true): **~41s** (~10s/trang), wall 472s, KHÔNG OOM.
  → T4 đã bão hoà với 1 trang/lần cho loại trang này; gộp lô không nhanh hơn ⇒ giữ `KAGGLE_BATCH_PREDICT=false`.
  Watchdog process-level (300s/trang) đã có, không kích hoạt trong 2 run này.
- 2026-11-09 · Bug: `runtime_settings._parse` xét `isinstance(default,int)` trước bool → 'true' luôn trả default
  (cờ boolean không bật được từ DB) — đã sửa, có test.
- 2026-11-08 · Header 2 cột đề thi → **bảng 2 ô không viền** (job 86 render đúng: BỘ GIÁO DỤC… |
  KỲ THI…). Proofread **song song** (concurrency 3): job 90 = 336s / 89 gợi ý (tuần tự ~27 phút).
- 2026-11-08 · Bench GPU: 8 trang (trang 7–14 của job 90) đang chạy >30 phút ở chế độ TUẦN TỰ →
  T4 16GB xử lý ~35–45s/trang; chưa đo được batch (predict nhiều trang) vì Kaggle trả output của
  version kernel trước (dataset mount chưa sẵn sàng) — đã thêm DATASET_READY_WAIT=90s.
- 2026-11-08 · **Flow gợi ý sửa lỗi tiếng Việt (proofread) đã chạy lại**: trước luôn 0 gợi ý vì
  (a) runtime setting `proofread_llm_model` = model free OpenCode (`zen/longcat-2.5-preview-free`) → 429/503,
  (b) router trả body = JSON + `data: [DONE]` → `resp.json()` ném Extra data → mất hết.
  Fix: DB setting → `role-scout`; `_response_json()` chấp nhận JSON/SSE/JSON+đuôi rác; `_parse()` cắt
  object đầu tiên. Verify job 91: **19 gợi ý** (HỆT→HẾT, xào xac→xào xạc, in đạm→in đậm…).
  Ưu tiên tiếp theo của user: 2 cột header đề thi bị LỆCH (job 86) — ảnh chỉ là test, không cần đầu tư.
- 2026-11-08 · Job 88 chạy lại (queue GPU ~50 phút + OCR ~15 phút) → **verify chữ-trong-ảnh vào DB/API**:
  `p1_b2` (ảnh bo mạch) kind=graphic ocr_text="005 | 11 | y | 1 | O | CH5a…" (rác, KHÔNG vào thân);
  `p1_b18` (bản vẽ) kind=graphic ocr_text="202.70 | 200 | 189.90 | 503.40 | 506…" (số thật, giữ metadata).
  docx 2 trang, ảnh bo mạch/badge/logo hiện đầy đủ, thân văn bản KHÔNG có số đo bản vẽ.
- 2026-11-08 · **Job 90 'ảnh mất một khúc + không nhận ra trang ngang'** — 3 nguyên nhân riêng biệt:
  (a) mọi trang ép A4 DỌC (p1 chứng chỉ là trang ngang 2339×1653) → giờ nhận orientation + khổ ngang;
  (b) style Normal đặt line_spacing EXACT → paragraph chứa ẢNH bị co dòng, ảnh đẩy lên toạ độ ÂM
      (PDF rect y0=-265) nên KHÔNG vẽ → bỏ line_spacing khỏi Normal; ảnh còn bị cắt khi rộng hơn CỘT
      → `_limit_width = min(vùng chữ, cột)`;
  (c) rembg khoét lỗ trắng trong screenshot → chỉ xoá nền khi viền ảnh sáng+đồng nhất.
  Đo lại: p1 842×595 landscape, p3 screenshot đầy đủ, job 88 ảnh bo mạch/logo hiện đủ (trước là dải mỏng).
  Job 90 docx 20 → 27 trang (ảnh giờ thật sự được vẽ nên chiếm chỗ).
- 2026-11-08 · Chốt cách xử lý chữ-trong-ảnh: kernel OCR vùng ảnh ≥5% diện tích trang rồi PHÂN LOẠI
  ("document" = ≥3 dòng, ≥2 dòng ≥25 ký tự, token số <40% → thêm region `<rid>_text` vào thân;
  "graphic" = còn lại → chỉ lưu `ocr_text` metadata). Verify job 88: b2 (ảnh bo mạch) OCR ra rác
  "005 | 11 | y | 1 | O | CH5a" → graphic (không vào thân ✓); b18 (bản vẽ) OCR ra đúng 202.70/200/189.90
  → graphic, giữ metadata. Cần 1 lần chạy lại job 88 để `ocr_text` vào DB/API (schema đã cho phép).
- 2026-11-08 · Mục tiêu chốt với user: **luôn lấy được VĂN BẢN**, không biến trang thành ảnh. Docx giờ
  dựng geometry + cỡ chữ THEO TỪNG TRANG (job 90: trang chứng chỉ ngang + 19 trang text dọc).
  Đo độ đầy đủ job 90: 13.5k ký tự docx vs 9.5k ký tự text gốc (gốc có trang scan 0 ký tự → OCR bù).
  Gap còn lại: chữ NẰM TRONG vùng ảnh (số kích thước trên bản vẽ kỹ thuật job 88) không được OCR
  → job 88 đạt 82% token gốc.
- 2026-11-08 · **Job 91 (đề văn) fix xong**: trang 1 cột bị tách 3 cột giả → thân bài nhồi cột 432px
  (chữ gãy dòng, đảo thứ tự). Fix: ≥2 block rộng ≥60% ⇒ 1 cột → 1 trang đúng thứ tự.
  **Job 90 (20 trang, p1 = chứng chỉ scan, p2..20 = trang text)**: trang text OK nội dung nhưng chữ nhỏ
  (geometry/font lấy từ TRANG 1 cho cả document) → cần geometry theo TỪNG trang; p1 là đồ hoạ nên vẫn xấu.
  **Job 88 (datasheet)**: 1 trang, bảng gọn, ảnh đủ.
- 2026-11-08 · **2 job user push (#87 thẻ SV HEIF, #88 datasheet PDF)** đã chạy tự động xong. Fix trong lúc
  theo dõi: (a) crop dùng bbox thô trên ảnh gốc lớn hơn frame OCR → vùng QR lệch (scale
  img.width/page.width), (b) PyMuPDF không mở HEIF → kernel crop bằng PIL fallback, (c) presign manifest
  batch 900s hết hạn khi hàng đợi GPU dài (#88 403 → kernel bỏ job) → `batch_input_url_expires` 6h,
  (d) font docx tính cả node table/image → bảng tràn 2 trang; cột thoái hoá (2 dải hẹp) → fallback 1 cột.
  Còn lại: OCR sai dấu vài chỗ (THỂ/Thè/bảo quàn), heading giả trên thẻ (bbox không có info dòng),
  datasheet nhiều ảnh vẫn thô về bố cục (chấp nhận: bản chất là brochure đồ hoạ).
- 2026-11-08 · **Header đề thi mất là do UVDoc (use_doc_unwarping)**, không phải code: cùng trang job 86
  unwarp ON = 21 block (mất header, box kẹp mép y0=1), unwarp OFF = 23 block (có header). Mặc định giờ
  unwarp=False, `--opt unwarp=true` cho trang cong. docx 1 trang đủ header + gạch chân.
- 2026-11-08 · Batch = dev/thủ công (`run_one.py --job N` claim→OCR→POST result), session = product.
  `deploy/.env.dev` đặt `KAGGLE_MODE=batch` + `KAGGLE_KERNEL_REF=jhandf/img2text-batch` → job upload tự
  chạy (job 86: queued → extracting → done KHÔNG cần tay). Còn lại: header trang bị PaddleOCR-VL bỏ
  (`86_raw.json` chứng minh `parsing_res_list` không có block header) — lỗi model, không phải code.
- 2026-11-08 · **Worker thật đã chạy job 86** bằng Kaggle batch (không cần backend public):
  dataset `jhandf/img2text-input-j86` (`86__job86.jpg`) + kernel `jhandf/img2text-batch-j86`
  (T4, v2 sau khi dataset kịp index — v1 nhận `invalidDatasetSources` → kernel chạy rỗng).
  Output: 21 block PaddleOCR-VL → bơm vào `/api/jobs/86/result` (claim bằng runner key) →
  docx-layout **1 trang** khớp bản gốc. Script: `/tmp/kbatch.py`, `/tmp/kpush2.py`.
  (Lệnh tái sử dụng: `docker exec img2text-dev-server-1 python -u /tmp/kpush2.py`.)
- 2026-11-08 · **Job 86 (đề thi 1 cột, 1242×1713)**: upload OK sau fix sha256; nhưng đứng `queued`
  vì `KAGGLE_KERNEL_REF` bị comment trong `deploy/.env.dev` → `kaggle_enabled=False` → scheduler
  không spawn kernel, dev compose cũng không có worker container. Đã bơm result tesseract
  (`/tmp/tess_worker.py`) để test đường layout/docx. docx-layout: 3 trang → **1 trang** sau fix
  khung trang. Việc còn lại: bật kernel thật (uncomment KAGGLE_KERNEL_REF + push kernel).
- 2026-11-07 · **Job failed vì ảnh cụt**: 29 job (bang-luong.png ×14, hoa-don-1.png ×15) cùng trỏ
  `uploads/a4bcd7b8…png` = **70 byte** (đúng chữ ký PNG, hết ngay sau IHDR) → kernel chết
  "broken data stream when reading image file". Magic-byte sniff cũ chỉ so chữ ký nên cho qua.
  → Fix: `jobs._undecodable_image()` (PIL open+verify) trong `create_job`, ảnh không decode được →
  422 + xoá object, không tạo row. Đường PDF không đổi (pypdf/header, xem ponytail).
- 2026-11-07 · **Docx giữ layout: dải ngang (band) thay vì 1 grid cột/trang.** `layout_spec._zones()`
  chia trang theo khoảng trống dọc (ratio 1.2 × median line height); mỗi zone có grid cột riêng
  (`_zone_cols`); `PageSpec.bands` + `Band`; block sắp theo (band, col, y, x) → thứ tự đọc đúng.
  IR page có `bands: [{y0,y1,columns,node_ids}]`, node có `render.style.band`.
  `render_docx_ir` phát 1 SECTION / dải (grid cột riêng), page break giữa trang OCR.
- 2026-11-07 · Sửa nhận cột: `_cluster_columns` gộp theo **mép trái** (tol 3% bề ngang trang) thay vì
  "interval chồng nhau" (byline vắt rãnh nuốt 2 cột thành 1); `_col_index_of` chọn cột **chồng nhiều
  nhất** (trước: cột đầu tiên chứa tâm → cột thật bị xoá oan); `_set_section_cols` **chuẩn hoá** bề
  ngang + rãnh cột cho vừa vùng chữ Word (trước dùng px tuyệt đối → 4 cột chỉ chiếm 52% bề ngang,
  LibreOffice vẽ chồng chữ).
- 2026-11-07 · Vòng **VLM preview** để kiểm layout Word: `deploy/dev/docx-render/Dockerfile`
  (LibreOffice + fonts Noto CJK) + `server/scripts/docx_layout_preview.py` (job → .docx → PDF → PNG
  cạnh trang gốc rasterize). Chạy trong container dev rồi render qua image `img2text-docx-render`.
- 2026-11-07 · **Hướng A (user chốt): IR là nguồn render duy nhất.** `spec_ir` giờ sinh node có
  `text` + `render{kind, bbox_exact (float), lines, style{align,indent_px,first_line_indent_px,font_px,
  level,space_after_px,col_index,tabs},latex,html,cells,image_region_id}`; page có `width/height/columns`.
  `IR_SCHEMA_VERSION = "1.1"`; `GET /ir` dựng lại cache khi schema khác.
- 2026-11-07 · `render_md.py`: `render_md_ir(ir)` (walker node) là đường duy nhất, `render_md_spec(result)`
  = wrapper `spec_ir` → IR. `render_docx.py`: `render_docx_ir(ir, style_overrides, crops)`; `_block_of(node)`
  adapter node IR → BlockSpec để walker docx giữ nguyên; `_load_crops` cũng đi qua IR. `build_page_specs`
  KHÔNG còn trong đường render (chỉ dùng khi sinh IR).
- 2026-11-07 · **Ảnh không bao giờ hiện trong md/docx (job PDF)**: worker local chỉ ghi marker text
  (crop chỉ có từ Kaggle kernel); fallback `get_or_make_crop` mở file gốc bằng PIL → PDF thì
  `UnidentifiedImageError`; route `/regions/{rid}/crop` chặn `file_type != "image"` (ruling R26).
  → Fix: `_pdf_page_png()` rasterize trang bằng PyMuPDF (zoom theo `page.width` để bbox px dùng trực
  tiếp), `get_or_make_crop` nhánh PDF, bỏ gate R26 ở route; lỗi rasterize → KeyError (404, không 500).
  PyMuPDF đã có sẵn trong server deps → không thêm dependency.
- 2026-11-07 · Ruling R26 (PDF không crop được) **bị bãi bỏ** — thay bằng "PDF rasterize at request".
- 2026-11-07 · **Thứ tự đọc = thứ tự layout**: `layout_spec.reading_order_region_ids()` (spec col→y→x,
  region ngoài spec nối sau sort y0,x0); `layout_sync.text_from_regions()` dùng nó; `jobs._extraction_text`
  delegate → text trong editor và layout cùng thứ tự (trang 2 cột trước đây lệch).
- 2026-11-07 · **Neo theo nội dung thay vì vị trí**: `apply_text_to_regions` tìm từng region text trong
  text cũ bằng `_find_run` (khớp liên tiếp, không tìm thấy từ cursor thì tìm lại từ 0) → không phụ thuộc
  thứ tự đã lưu (row-major cũ vẫn đúng). Không neo được gì → return False (không xoá text region).
- 2026-11-07 · **Chữ mới trên ảnh**: span replace bắt đầu ở dòng KHÔNG có chủ (dòng trống của vùng ảnh)
  → neo vào `prev_owner` (region trước ảnh), không đẩy xuống region dưới ảnh.
- 2026-11-07 · Thứ tự gọi trong `post_extraction`: `apply_text_to_regions` PHẢI chạy TRƯỚC khi ghi
  `result["extraction_text"]` (cần text cũ để neo; ghi trước → diff rỗng → mất sạch text region).
- 2026-11-07 · Neo theo BBOX (user chốt): khi một opcode `replace` trải nhiều region, chia dòng mới theo
  **chiều cao bbox** (`y1-y0`) thay vì số dòng cũ; bbox thiếu/hỏng → fallback số dòng. Helper
  `layout_sync._bbox_height()`. Dòng không đổi vẫn giữ region gốc qua diff (equal), nên neo chỉ áp cho
  phần bị viết lại.
- 2026-11-07 · Siết anchor (hướng A): replace trải nhiều region → chia tỉ lệ theo số dòng cũ của từng
  region; region text rỗng (placeholder ảnh) = owner None → không nhận chữ; insert ở đầu → region đầu.
- 2026-11-07 · Full save gặp 409 `detached` → `window.confirm` rồi gửi lại `force=true` (helper
  `isDetached()` trong `web/src/lib/errors.ts`, dùng chung với phrase-sync).
- 2026-11-07 · Xoá badge `stale-badge` + nút `btn-resync-layout` + 3 key i18n (`staleBadge`, `resync`,
  `resyncDone`): layout tự rebuild khi save text nên badge gần như không còn nghĩa. Server vẫn trả
  `stale_layouts` (contract, không phá API).
- 2026-11-07 · **Bug workflow (job #84)**: sửa text ở Overview KHÔNG tới layout. 3 nguyên nhân:
  (1) `POST /extraction` chỉ ghi `result.extraction_text`, render đọc `pages[].regions[].text`;
  (2) `TextSection.saveFullText` không gửi old/new phrase → server bỏ qua cả sync lẫn cờ rerender;
  (3) `retry-layout` → `auto_generate_output` → `build_md(result)` từ regions cũ → ra đúng byte cũ
  (7 lần bấm = 7 version docx y hệt).
- 2026-11-07 · **Fix (hướng A user chốt)**: `layout_sync.apply_text_to_regions()` diff theo DÒNG từ text
  phẳng → regions (insert neo vào region dòng trước, insert đầu → region đầu), giữ anchor ảnh/bảng;
  `post_extraction` full-save → gọi nó rồi `auto_generate_output` (0 LLM) dựng lại md-layout + docx-layout;
  thêm `doc_versions.mark_layout_current()` ghi head row `based_on_text_version` mới (bytes trùng → UPDATE
  thay vì đẻ row) → stale badge không treo.
- 2026-11-07 · Thanh 1 bỏ luôn badge `Layout saved` + nút `Preview` (yêu cầu user): chỉ còn `Save` (md).
  MDEditor đặt `preview="edit"` cố định → 1 khung soạn, không còn split SOURCE|PREVIEW. Hợp đồng
  `onActionsChange` gọn lại `{mode, save, saving}`.
- 2026-11-07 · Bỏ hàng điều khiển riêng của editor (`Markdown | Editor … Preview | Layout saved | Save`):
  `UnifiedEditor` publish `{mode, cached, preview, save, saving}` qua prop `onActionsChange`, `JobDetail`
  render badge + Preview + Save ở thanh 1 (chỉ md mới có Preview/Save; word dùng nút ở footer tờ giấy).
  `btn-edit-doc` (Done) đổi sang `variant="secondary"` — **Done chỉ điều hướng /edit ↔ /layout, KHÔNG lưu**.
- 2026-11-07 · Review loop (parent-orchestrated, 2 vòng + 1 lần chạy lại): thanh 1 đổi Done/History/Download
  sang icon-only (worker), 3 reviewer fresh-context. Chốt: 1 P1 thật (đã sửa), 2 P2 đã sửa, 4 claim reviewer
  SAI đã bác bỏ bằng grep/git diff, 3 P2 defer. Verdict cuối: **OK with notes** — không còn P0/P1.
  Sửa sau review: `web/scripts/landing-shots.mjs` (2 wait chết `page-preview`/`page-count` → `word-toolbar`
  + `.wp-paper`) và `DownloadDropdown.tsx` (thêm ChevronDown, `h-8 w-8` → `h-8 px-2`).
- 2026-11-07 · Xong đợt refactor UI (chưa commit): gộp trang Text vào Overview; Edit = sửa văn bản
  gốc; nút chuyển MD⇄Word lên thanh hành động (nhãn ghi đích); bỏ toggle một chiều
  `forceWord`; ảnh gốc chia 2 pane kéo tỉ lệ (`SplitPane`, lưu localStorage); toolbar nhóm
  phương án A (11 mục, align/list thành dropdown, `Page & text style` thành popover "Trang");
  toolbar dock 4 phía, dính sát vùng page; page cuộn BÊN TRONG `.wp-paper-scroll`; thanh trên
  thu gọn được khi fullscreen. Verify: tsc clean, vitest 457/457, `audit:a11y` → DONE 0.
- 2026-11-06 · **UI không lỗi — load 3–4 phút là do dev server + Tailscale relay.** Peer `nguyenducduy`
  (`100.72.17.32`) đi qua **DERP(sin), không có direct connection** (`tailscale ping` → 146–1201ms).
  Vite dev bắn **140 request / 42MB cold, 14MB warm** → qua relay thành vài phút. Đã chuyển sang
  **`vite preview` (bản build) trên `100.86.205.2:5173`: 11 request / 1697KB**, dcl 727ms, paper 2827ms.
  Còn phải làm: `preview/layout.html` trả 500 (PIL crop) nên web fallback export+download, tốn ~1.2s
  trước khi WordEditor mount.
- 2026-11-06 · Word editor chỉnh theo Google Docs: bỏ khung scroll lồng — `.wp-paper-scroll` cuộn ở
  cấp trang; giấy A4 794×1123, `border-radius:0`, shadow 2 lớp; toolbar 1 dải phẳng chỉ
  `border-bottom`, ô "Normal text/H1-H3" ra đầu hàng; form `DocStyleTools` gấp vào `<details>`
  "Trang & kiểu chữ"; nút lưu gom về footer giấy ("Lưu kiểu trình bày" + "Lưu nội dung").
  Còn 1 finding chưa làm: toolbar 390px vẫn phải vuốt ngang mới tới B/I/U (test cấm `flex-wrap`).
- 2026-11-04 · Xong bộ skill `pi-flow` ở `.agents/skills/flow*` (7 skill, 412 dòng): `flow` (điều phối)
  → `flow-grill` (pha 1–4) → `flow-spec` (5) → `flow-coldread` (6) → `flow-execute` (7) →
  `flow-verify` (8) → `flow-ship` (9, thêm mới: commit/PR/deploy + đường lùi + đóng flow).
  Chưa chạy end-to-end một flow thật; chưa có extension `flow-gate` chặn `edit`/`write`.
- 2026-11-04 · Xong `docs/REVIEW-ui-current-state.md` (review-only, 230 dòng): 4 section bắt buộc,
  80 tag spec-backed/observed-only, 27 citation `web/src/`. Chờ user chọn hướng fix từ §Prioritized
  remediation (P0 = gộp 3 nút lưu layout + dirty-state). Mâu thuẫn cần user chốt: SPEC §3.4
  "bỏ tab MD/Word" ↔ spec route-split AC1–AC2 "mode phải addressable".
- 2026-11-03 · Xong spec+plan+implement+2 vòng review cho audit drift (xem
  `docs/superpowers/specs/2026-11-03-audit-drift-hardening-design.md` +
  `plans/2026-11-03-plan-audit-drift-hardening.md`). 5 lane song song bằng subagent,
  2 real defect đã sửa sau review. Chờ user duyệt G1–G6 (plan §Approval-gated).
- 2026-11-03 · agentmemory **đang tắt** cho repo này qua `.pi/mcp.json` (`enabled: false`) —
  verify bằng `pi mcp list` → `agentmemory: disabled (codemode, global) / project override`.
- 2026-11-03 · Tạo `AGENTS.md` ở root img2text: gate UI review = Playwright làm bằng chứng
  (`scripts/audit-shots.mjs` + `npm run audit:a11y`) → `ui-ux-review` ra finding →
  `design-taste-frontend` định hướng fix + §14 pre-flight → chụp lại so before/after.

## Decisions
- 2026-11-07 · Reviewer agent mặc định model `opencode/muse-spark-1.3-contributor-free` KHÔNG có trong registry
  session này → phải truyền `model: "9router/KG/claude-sonnet-4.5"` cho mọi lần gọi `reviewer`. Ghi nhớ khi
  chạy lại loop.
- 2026-11-07 · Workflow script: `runs.run` phải được gán (`const impl = await runs.run(...)`) trước `runs.all`,
  nếu không script chết `ReferenceError` và trả "workflow completed" mà worker chưa từng chạy.
- 2026-11-07 · Reviewer trả file artifact 0 byte khi nó chỉ trả progress note; brief phải ghi rõ
  "reply MUST be the full report, not a progress note" để lấy được nội dung.
- 2026-11-07 · `--paper-h` (min(78vh,900px)) là chiều cao vùng hiển thị của page, dùng chung cho
  `.w-md-editor` (phải `!important` vì MDEditor set inline `height:100%`) và `.ed-work`.
- 2026-11-07 · `SplitPane` luôn render `second` ở cùng vị trí cây React, `first=null` khi tắt split →
  bật/tắt ảnh gốc KHÔNG remount editor (remount sẽ chạy lại export và mất nội dung đang sửa).
  Khi không split thì không khoá chiều cao (khoá → panel tràn, footer đè hàng Save ở mobile).
- 2026-11-07 · Nút chuyển mode nằm ở `JobDetail` action bar; test `UnifiedEditor` lái mode bằng
  nút `harness-switch-*` trong harness (mô phỏng điều hướng), không phải UI thật.
- 2026-11-06 · Xem qua Tailscale thì chạy `vite preview` (build) chứ không `npm run dev`: dev phục vụ từng
  module rời, 140 request qua DERP relay = vài phút. `preview` cần `preview.proxy` cho `/api`
  (đã thêm vào `vite.config.ts`, cùng `allowedHosts`).
- 2026-11-06 · `/api/jobs/{id}`: 3 HEAD lên R2 đổi tuần tự → `asyncio.gather` (380–740ms → 143–190ms).
  HEAD `docx-layout` giờ luôn chạy (trước chỉ khi thiếu docx.html) — đổi 1 round trip lấy song song.
- 2026-11-06 · Lề giấy Word lấy từ `layout_style.margin` (cm), không hard-code: `scopeWordPaneCss`
  scope `body` → `.word-doc` = chính `.wp-paper`, nên 2.5cm = 94px mỗi bên. Mobile override
  `.word-doc.wp-paper` về 20px (specificity 0,2,0 thắng `.word-doc` 0,1,0 → không cần `!important`).
- 2026-11-06 · Nút lưu: giữ 2 chức năng riêng (PUT docx.html vs PATCH layout-style) nhưng dồn về
  cùng footer của tờ giấy; không gộp thành 1 request vì sẽ đổi hành vi + phá test.
- 2026-11-04 · Review UI dừng ở mức tài liệu, không sửa code · constraint của task; mọi finding
  phải có `file:line` đọc trực tiếp, số liệu từ MEMORY.md cũ phải đánh dấu "chưa xác minh lại".
- 2026-11-03 · Tắt agentmemory bằng project override `.pi/mcp.json` thay vì sửa `~/.pi/agent/mcp.json`
  · chỉ ảnh hưởng repo này, bật lại bằng cách đổi `enabled: true` hoặc xoá file.
- 2026-11-03 · Thêm `typescript` vào `.serena/project.yml` (trước chỉ `python`) · web/ có 144 file
  .ts/.tsx, thiếu TS server thì serena mù nửa repo; đã verify `get_symbols_overview` trên
  `web/src/api/types.ts` chạy được.

## Measured
- 2026-11-08 · job 90: 20 trang → docx 20 trang; job 91 → 1 trang; job 88 → 1 trang; job 86 vẫn 1 trang.
- 2026-11-08 · scheduler tick 60s chạy đúng; `kaggle_min_gap_seconds=600` chỉ HOÃN spawn (job 90/91 chờ
  ~5 phút mới được push) — không phải bug. Log app đi vào /app/logs/*.log (không phải stdout).
- 2026-11-08 · job 87: 15 text node + 1 image (QR), md 36KB; job 88: 29 node (15 text, 11 image, 1 table
  28 hàng), docx 2 trang → **1 trang** sau fix. server pytest 1008, deploy/kaggle 60.
- 2026-11-08 · OCR ra 21 block (unwarp on) vs 23 (off); thời gian kernel ~13 phút/lần chạy.
- 2026-11-08 · Job 86 batch tự động: ~13 phút/trang (venv+deps ~300s + OCR). docx-layout 1 trang.
- 2026-11-08 · server pytest **1003**, deploy/kaggle pytest **57**.
- 2026-11-08 · Kernel batch: venv+deps ~300s, tổng ~620s/job ảnh 1 trang trên T4.
- 2026-11-08 · job 86 VLM: text_version 0, IR 21 node / 1 band / 1 cột; docx 1 trang.
- 2026-11-08 · server pytest **995**.
- 2026-11-08 · docx job 86 @805fa8d = 3 trang; sau fix geometry = **1 trang** (font 9,2pt từ nhịp
  dòng 24px, lề A4 834/527/614/297 twips, vùng chữ ~7,1in). job 84 vẫn 2 trang, band 4 cột nguyên.
- 2026-11-08 · Ép vùng chữ 6in (template cũ) làm chữ phải nhỏ ~35% mới vừa; cỡ chữ suy từ bbox
  height cho 13,5pt (tràn), từ pitch/1,25 cho 9,2pt (vừa) — đo bằng sweep 6,5→10pt.
- 2026-11-08 · server pytest **994** (2 test mới: geometry + metrics).
- 2026-11-07 · Upload path đo lại: PNG 638 byte → PUT → đọc lại đúng 638 byte (không bị cắt hiện nay);
  object 70 byte là từ lần upload cũ/hỏng sẵn.
- 2026-11-07 · server pytest **992** (thêm tests/test_jobs_upload_decodable.py; sửa test_presign_upload
  dùng PDF cho test biên 50MB).
- 2026-11-07 · job #84 docx sau band: 3 section (1 cột đề bài / 4 cột thân / 1 cột dòng kết),
  cols 4 cột equalWidth=0, ảnh nhúng trong dòng, đọc đúng thứ tự; trước đó: 2 cột hẹp (213/211 px)
  với rãnh 2400 twips + chữ tràn loạn.
- 2026-11-07 · Ép cỡ chữ/giãn dòng theo bbox → **tệ hơn** (chữ tràn sang cột bên, cột lệch đỉnh) →
  đã revert, ghi lý do trong code.
- 2026-11-07 · server pytest **990** trong worktree `.worktrees/docx-layout` (nhánh feat/docx-layout).
- 2026-11-07 · Parity sau refactor IR: job #84 md-layout **giống hệt** trước (chỉ khác payload ảnh);
  docx `document.xml` **byte-identical** (so sau khi bỏ whitespace) khi cấp cùng crop.
- 2026-11-07 · IR job #84: schema 1.1, 34 node, width 1653, 2 columns, node có `text` + 8 key style.
  Payload /ir 27.6 KB (trước ~8 KB).
- 2026-11-07 · server pytest **984** (thêm `tests/test_ir_render.py` 5 test), web vitest 453, audit:a11y 0 findings.
- 2026-11-07 · job #84 (PDF): crop p1_b7 → 200, JPEG 18635 bytes (ảnh thật); md-layout 0 marker,
  có `![vùng p1_b7](data:image/jpeg;base64,…)`; `/preview/layout.html` 200 (trước 500) với `<img>` presigned;
  docx-layout có `word/media/image1.jpg` + `<w:drawing>`.
- 2026-11-07 · server pytest **979** (thêm `tests/test_crop_pdf.py` 2 test; sửa `test_crop.py` fixture PDF thật).
- 2026-11-07 · job #84: chèn "DONG MOI TREN ANH 1/2" ngay trước vùng ảnh (dòng 6) → md-layout có chữ
  ở idx 215, marker ảnh idx 432 → **trước ảnh**; revert sạch (0), marker còn (1), tv 12, stale=[].
- 2026-11-07 · gate cuối: server pytest **976**, web vitest **453**, tsc clean, audit:a11y 0 findings.
- 2026-11-07 · test bbox: 3 region cao 100/400/50, mỗi region 5 dòng cũ, rewrite 20 dòng → chia 4/15/1
  (không phải 5/5/5); nối lại đúng nguyên văn. server pytest **972**.
- 2026-11-07 · job #84: sửa "Cau 3."→"Cau 3 (bbox)." → md-layout có bản sửa, marker ảnh còn, regions
  nhận đúng (region text "Cau 3 (bbox). Chung minh tam…"); revert sạch, stale=[].
- 2026-11-07 · job #84 sau siết anchor: sửa "Cau 2."→"Cau 2 (sua)." → md-layout có bản sửa (1), marker
  ảnh `Hình ảnh chưa trích xuất` vẫn còn (1); revert → 0 / 1; `stale_layouts=[]`, tv 7.
- 2026-11-07 · gate: server pytest **970**, web vitest **453**, tsc clean, build OK, audit:a11y 0 findings.
- 2026-11-07 · job #84 end-to-end: save text sửa "90 phut"→"90 phut SUA" → md-layout chứa bản sửa (grep 1);
  revert → grep 0; `stale_layouts=[]` mọi lần; md-layout versions head `(2, based_on=3)`.
- 2026-11-07 · server pytest **969 passed** (thêm `tests/test_text_regions_sync.py`, 8 test).
- 2026-11-07 · `/jobs/84/edit/md` sau khi bỏ hàng: thanh 1 có switch-mode-word, badge "Layout saved",
  Preview, Save, Done(secondary), History, Download; hàng cũ đã mất (rowGone=true); trang 949px.
- 2026-11-07 · `/jobs/84/layout/md`: KHÔNG có badge/Preview/Save (đúng — trang xem, UnifiedEditor không mount).
- 2026-11-07 · **Root cause icon bé**: `Button size="sm"` = `px-3` (24px padding ngang). Nút vuông `h-8 w-8`
  (32px) + icon 16px → padding ăn 24px nên SVG bị flex bóp còn **8×18** (đọc được bằng
  `getBoundingClientRect` của svg). Sửa: `px-0` cho nút icon-only + `shrink-0` trên svg + icon 18px.
- 2026-11-07 · Sau sửa (Playwright `/jobs/84/edit/word` @1440): btn-edit-doc 32×32 svg 18×18,
  btn-version-history 32×32 svg 18×18, btn-download 66×32 svg[18×18,14×14], btn-zen 32×32 svg 16×16.
- 2026-11-07 · `vitest` 455/455 và `audit:a11y` `DONE 0 routes with findings` sau khi sửa icon.
- 2026-11-07 · Bar 1 sau khi icon hoá (Playwright, `/jobs/84/layout` @1440): btn-edit-doc 32×32 label
  "Edit" 1 svg; btn-version-history 32×32 "History" 1 svg; btn-download 62×32 "Download" 2 svg (icon+chevron).
- 2026-11-07 · Sau loop: `tsc` 0 lỗi, `vitest` 455/455 (61 file), `npm run build` OK.
- 2026-11-07 · CHƯA chạy `web/scripts/landing-shots.mjs` sau khi sửa selector (sẽ ghi đè ảnh đã commit
  trong `web/public/shots/`) → 2 selector mới chỉ verify bằng grep + trace component, chưa verify bằng chạy thật.
- 2026-11-07 · Word editor @1440: toolbar 1150×45, `.wp-paper-scroll` cao 655 với `scrollHeight` 2837
  (cuộn nội bộ), trang chỉ 1015px. Dock trái: toolbar 48×700, paper-scroll 1102×700.
- 2026-11-07 · MD editor @1440: `.w-md-editor` 702, scroll trong 2137, trang 971px (trước: trang 2453px).
- 2026-11-07 · Toolbar cần ~1136px cho 17 mục cũ; phương án A còn ~618px cho 11 mục → vừa tờ giấy 794px.
- 2026-11-06 · Load `/jobs/84/edit/word` @1280 qua tailnet: dev = 140 req / 42358KB cold /
  14103KB warm, dcl 1905ms, paper 4063ms. Build+preview = 11 req / **1697KB**, dcl 727ms,
  fcp 868ms, paper 2827ms.
- 2026-11-06 · Bundle build: `index` 3600KB (gzip 1195KB) + `src` 510KB (100KB) + css 76KB (14KB)
  + `pdf.worker` 1178KB. Dev warm 14MB → build 1.7MB = **8×**; dev cold 42MB → **25×**.
- 2026-11-06 · `/api/jobs/84` (27KB payload): 380–740ms trước, **143–190ms** sau `asyncio.gather`.
- 2026-11-06 · `preview/layout.html` job #84: **500** sau 585ms (`PIL.UnidentifiedImageError`,
  `exports.py:192`), web gọi 2 lần → ~1.2s phí trước fallback. Chưa sửa.
- 2026-11-06 · Word editor @1440 sau sửa: `.wp-paper` 794px, `.wp-paper-scroll` cao 2944 = đúng
  `scrollHeight` (trước: khung 666px nhốt nội dung 2864px). Mobile @390: `.ProseMirror` 318px
  (trước 169px), trang 4329px (trước 7747px).
- 2026-11-06 · `npm run audit:a11y` (SHOT_EMAIL=ui-demo@example.com) → `DONE 0 routes with findings`;
  vitest 457/457; tsc clean.
- 2026-11-06 · Rate limit auth 10/1h in-memory theo process → cạn quota login thì
  `docker compose -f deploy/docker-compose.dev.yml restart server` là reset (đã dùng).
- 2026-11-06 · `ocg/kimi-k3.1-pro` + `ocg/kimi-k3`: hết quota opencode-go (`GoUsageLimitError`) →
  review UI dùng `KG/claude-sonnet-4.5` (vision, chạy được 9 ảnh + 7 file code).
- 2026-11-04 · discovery skill: `pi -p -t read "list skill flow*"` → **7/7 tên đúng**, nên `.agents/skills/`
  trong project root được pi load (không cần `~/.pi/agent/skills/`). Lưu ý: `--no-tools` làm pi **bỏ
  luôn skills hint** khỏi system prompt → probe bằng `-p --no-tools` cho kết quả sai "None".
- 2026-11-04 · frontmatter 7 `SKILL.md`: name==tên thư mục, desc 197–316 ký tự, không lỗi spec
- 2026-11-04 · `audit-a11y.mjs:95` báo sai mọi `<input>` có `<label>` → **đã sửa**: dùng `el.labels`
  thay `textContent` (sau khi kiểm `ariaSnapshot()` chứng minh 2 input có tên thật).
- 2026-11-04 · `npm run audit:a11y` **sau khi sửa checker** · `DONE 4` → `DONE 2` → (sửa J4b) `DONE 0`.
  2 route trung gian là cùng 1 lỗi J4b (nút inline 23,8px), không phải lỗi label.
- 2026-11-04 · `npm test` sau khi sửa `scripts/audit-a11y.mjs` · **450 pass / 60 file** (script không nằm trong suite)
- 2026-11-04 · `cd web && npm test` sau khi viết review doc · **450 pass / 60 file**, 57.7s
  (khớp baseline trong MEMORY, không có test nào bị task này đụng)
- 2026-11-04 · i18n parity vi↔en · **569 key mỗi bên, lệch 0** (script `node -e` duyệt dict)
- 2026-11-04 · component §8 SPEC không tồn tại trong repo: `SplitPane.tsx`, `StatBar`,
  `RowActionMenu`, `EditorToolbar` — **0/4 có mặt**; testid `panel-export` cũng không còn
- 2026-11-03 · jobdetail route split · vitest **450 pass/60 file** (+6 test mới), tsc + oxlint sạch
- 2026-11-03 · Overview rail · `gridTemplateColumns` @1440 **564px+564px → 776px+352px**;
  320 giữ nguyên (ảnh before/after byte-identical)
- 2026-11-03 · audit:a11y trước/sau đổi rail · **5 route → 4 route** có finding (không phát sinh mới).
  Finding còn lại: `jobs-search` (/jobs) và `input-current-password` (/profile) thiếu label — pre-existing.
- 2026-11-03 · AC7 · `pytest tests/test_preview_layout_html.py` = **3 passed** (Postgres test :5433 bật)
- 2026-11-03 · AC1 · migration apply 2 lần trên schema `create_all` → OK idempotent; simulate legacy
  (drop 11 cột + bảng) → apply → `text_version`/`rerender_requested`/`ocr_enabled` **null=NO**
  đúng model, `mode`/`output_format` có default, `worker_heartbeats` 4 cột đúng → **VERIFIED**
- 2026-11-03 · sau AC1 · `pytest test_preview_layout_html.py + test_models.py` = 4 passed (không vỡ)
- 2026-11-03 · G1 · `pw_watch_trg`/`pw_watch_fn`/`pw_watch` đã drop khỏi `img2text_dev`, users vẫn 4 row
- 2026-11-03 · G3 · xoá 23 branch đã merge (giữ `lane-deps` vì đang checkout trong worktree)
- 2026-11-03 · G4 · `.worktrees/plan-auth`, `.worktrees/plan-pr` là thư mục **rỗng** → rmdir
- 2026-11-03 · CI chạy test cần DB thế nào: service `postgres:16-alpine` publish **:5436**
  (`.github/workflows/ci.yml:21`), `DATABASE_URL` (:26) → create_all → `psql docs/migrations/*.sql` → pytest
- 2026-11-03 · codegraph index · 332 files / 5.527 nodes / 13.296 edges (DB 15,84 MB)
- 2026-11-03 · size repo · 162 file .py (server+worker, trừ .venv) / 144 file .ts,.tsx (web/src, web/tests)

## Facts (stack + lệnh chạy)
- Kiến trúc: Browser SPA → Nginx → FastAPI (:8010) + Postgres 16 + Cloudflare R2 →
  worker Kaggle/Colab pull `GET /api/jobs/next` (Bearer RUNNER_KEY).
- dev: `cp deploy/.env.dev.example deploy/.env.dev` → `docker compose -f deploy/docker-compose.dev.yml up -d --build`
  (Postgres :5433, LocalStack :4566, API :8010); web: `cd web && npm run dev` (:5173, proxy /api).
- test: `cd server && .venv/bin/pytest -v` (cần Postgres :5433 qua docker-compose.test.yml) ·
  `cd worker && .venv/bin/pytest -v` · `cd web && npm test` · lint `cd web && npm run lint` (oxlint).

- 2026-11-03 · playwright ^1.64.0 đã có sẵn trong `web` devDependencies; scripts UI đã tồn tại:
  `audit-a11y.mjs` (8 route × 1440/320), `audit-shots.mjs` (4 width → /tmp/audit),
  `landing-shots.mjs` (→ web/public/shots), `capture.mjs` → không cần cài thêm gì.
- 2026-11-03 · `audit-a11y.mjs` luôn exit 0 — gate phải đọc dòng `DONE N routes with findings`.
- 2026-11-03 · route "/" là `Landing`; a11y audit phủ "/", /jobs, /jobs/5, /jobs/5/text,
  /jobs/5/layout, /storage, /profile, /admin (8 route).

## Dead ends
- 2026-11-04 · `audit-a11y.mjs` login **401** với `admin@dev.local` / `Audit-2024-pw` (password khác
  trong DB seed hiện tại) → dùng `SHOT_EMAIL=audit-1793684235751@example.com` (role user) là được.
- 2026-11-04 · login **429** sau ~2 lần gọi curl → `docker compose -f deploy/docker-compose.dev.yml
  restart server` (limiter trong RAM) · sau restart API cần ~5s mới lên, `:8010` trả 000 trong lúc chờ.
- 2026-11-04 · chạy audit bằng user role **user** → `/admin` redirect `/` nên kết quả route admin
  thực chất là landing; muốn audit /admin phải dùng admin thật.
- 2026-11-03 · `audit-shots.mjs shoot` không chụp `/jobs/:id` (chỉ 8 route list) → phải viết script
  riêng; và `audit-a11y.mjs` login bị **429** sau ~3 lần chạy (limiter RAM trong container API) →
  fix: `docker compose -f deploy/docker-compose.dev.yml restart server`.
- 2026-11-03 · Docker: container tạo trước khi daemon restart giữ network cũ đã mất →
  `up -d` fail "network … not found"; fix: `up -d --force-recreate` (data trong named volume nên an toàn).
- 2026-11-03 · G2 (xoá Kaggle dataset `jhandf/img2text-wheelbuild-env` + 2 kernel) · **không làm được
  trên máy này**: không có `kaggle` CLI lẫn `~/.kaggle/kaggle.json`. Cần token hoặc làm trên web UI.
- 2026-11-03 · subagent `reviewer` mặc định (`bench/opencode/muse-spark-1.3-contributor-free`)
  → HTTP 400 "Model is unavailable" trên cả 3 reviewer. Dùng `model: "9router/KG/claude-sonnet-4.5"`
  (verify bằng curl). `9router/role-reviewer` → resolve ra `reflection/beam:free`, trả content rỗng
  khi `max_tokens` nhỏ.
- 2026-11-03 · `pi mcp list` không in gì khi chạy trong pipe có timeout sớm; phải redirect file
  rồi cat.

## Next
- Chạy thử `flow-grill` một lần trên vấn đề nhỏ (1 file, `lite: true`) và ghi lại chỗ agent nhảy pha.
- Cân nhắc extension `~/.pi/agent/extensions/flow-gate.ts` (`tool_call` → block `edit`/`write`
  ngoài `.pi-flow/` khi `state.md` phase < execute) — ngoài project root, cần user cho phép.
- 2026-11-04 · J4b **đã sửa**: `TextSection.tsx` nút `<mark>` thêm `py-0.5` → đo lại trong Chromium
  **27,80px** (từ 23,8px); `npm run audit:a11y` → **`DONE 0 routes with findings`**. `npm test` 450/60.
  Còn dưới 44px của DESIGN §7 — chấp nhận vì là control inline trong câu văn.
- Serena onboarding chưa chạy (`.serena/memories/` rỗng) — chạy nếu muốn serena tự ghi memory dài hạn.
- 2026-11-03 audit: 8 bảng + 3 cột trong `models.py` không có file `.sql` (users.ocr_enabled,
  jobs.preprocess/output_format/layout_style, worker_heartbeats chỉ có .md) → DB cũ thiếu.
- 2026-11-03 audit: CI thiếu `worker pytest` + `npm run lint` (README.md:66-68 nói có).
- 2026-11-03 audit: `docs/e2e-checklist.md` 0/69 box, section J retired nhưng còn đó; I5/K2 còn
  nhắc route `/edit` đã gỡ; M3-web (iframe) obsolete từ khi có Tiptap.
- 2026-11-03 audit: `.worktrees/plan-auth`, `.worktrees/plan-pr` là thư mục mồ côi (không còn
  trong `git worktree list`) — chỉ `lane-deps` là worktree thật.
- 2026-11-03 audit: item "mất dấu xuống dòng" đã sửa trong `layout_spec.py` (~dòng 370) — test
  chưa chạy được vì Postgres :5433 down (pytest cần test DB).
- Branch: 24/24 branch đều đã merge vào master → dọn được, không mất việc.

## Measured (2026-11-04, bench vLLM)
- `jhandf/img2text-bench-vllm` (T4, ảnh 31 regions): **native 49,2–50,0 s/ảnh** vs
  **vLLM backend 3,26–3,33 s/ảnh = ~15×**; nạp pipeline 34,2 s vs 11,9 s; vLLM cold start 180 s.
- Suy ra: **6 phút/trang của production không phải chi phí VLM** (VLM native ~50 s) → ~85% ở
  venv bootstrap / nạp model / preprocess / rembg / spawn kernel. Chưa đo từng phần.
- `deploy/kaggle/bench/` = bench tách rời, push bằng `docker exec deploy-server-1 python /tmp/bench/push_bench.py /tmp/bench`.
- T4 (CC 7.5) chạy được vLLM dù docs PaddleOCR khuyến cáo không nên; 3 lỗi cần fix:
  paddle ở venv riêng (không phá torch), `--served-model-name` nhiều alias,
  `--trust-request-mm-kwargs`, `--dtype float16`.
- 2026-11-04 · `jhandf/img2text-bench-stages` (T4, PDF 3 trang 2117×1900): **pip paddle 177,1 s**,
  bootstrap tổng **187,65 s**, load model **24,75 s**, import paddleocr 8,91 s,
  predict **54,6 / 52,9 / 53,3 s/trang**, preprocess cv2 **0,8 s/trang**, rasterize 2,4 s/3 trang.
  → cold start ~222 s/session; VLM chỉ ~19% job đầu; cv2 KHÔNG phải nút cổ chai (đính chính).
- 2026-11-04 · `jhandf/img2text-bench-crops` (T4): **rembg.remove ≈ 25 s/crop, không phụ thuộc kích
  thước** (256/512/1024 đều ~25 s) vì chạy CPU (`rembg[cpu]`, u2net resize 320²);
  `new_session()` **110,29 s** khi chưa cache u2net.onnx; fitz clip 0,06–0,27 s/crop.
  `kernel-session-metadata.json` có `dataset_sources: []` → session mode KHÔNG có cache u2net.
- 2026-11-04 · push → COMPLETE = 444 s với compute 409 s ⇒ **overhead Kaggle chỉ ~35 s**
  (bác bỏ giả thuyết spawn kernel 6 phút).
- 2026-11-04 · cold start session mode ≈ **321 s** (pip 177 + import 9 + load model 25 + u2net 110),
  chưa tính 53 s/trang VLM và 25 s/image block rembg.
- 2026-11-04 · `jhandf/img2text-bench-deps` (mount wheelbuild-env, 139 file): wheelhouse install
  **811,39 s** vs pip mạng **1063,74 s** (−24%); cùng lệnh pip mạng đo ở #stages chỉ **177 s**
  ⇒ **dao động 6×**. `import paddleocr` từ venv wheelhouse 11,5 s.
- 2026-11-04 · u2net: copy 176 MB từ `/kaggle/input` rồi `new_session()` = **174,95 s**,
  tải từ mạng = **94,17 s** ⇒ **cache trong dataset chậm hơn tải** (đính chính).
- 2026-11-04 · rembg: **cả trang 1524×1368 = 31,70 s** vs **3 vùng 456 px = 87,99 s** (2,8×).
  Production đang rembg từng image block (`extract_crops`), không phải cả trang.
- 2026-11-04 · rembg luôn resize input về **320×320** rồi phóng mask về kích thước input
  (`rembg/sessions/u2net.py:32,45`) ⇒ mask-px/ảnh-px: từng vùng 456px = 0,70 · cả trang 1524px = 0,21
  (thô hơn 3,3×). RGB không đổi ⇒ không vỡ ảnh, chỉ răng cưa biên alpha.
- 2026-11-04 · Chọn dataset vì **không phụ thuộc Internet**, không vì tốc độ (811 vs 1064 s).
  Chưa đo: đóng gói `venv.tar.zst` 1 file trong dataset để né FUSE 139 file.
- 2026-11-04 · `jhandf/img2text-bench-parallel`: song song (pip paddle ∥ rasterize+preprocess+u2net+rembg
  cả trang) → **tổng 280,97 s** vs tuần tự 432,21 s = **1,54×**, tiết kiệm **151 s**;
  stage-1 173,39 s ẩn hoàn toàn trong pip 186,10 s. `uv` **có sẵn** trong Kaggle image (bỏ pip uv).
- 2026-11-04 · Kaggle cho **2× T4** (`n_gpu=2`) nhưng session kernel chỉ 1 loop/1 claim → GPU #2 idle.
- 2026-11-04 · Tắt Kaggle orchestration ở **dev**: comment `KAGGLE_KERNEL_REF` trong
  `deploy/.env.dev:26` (feature self-disable khi kernel_ref rỗng) → `docker compose -f
  docker-compose.dev.yml up -d --force-recreate server`. Verify: `printenv KAGGLE_KERNEL_REF` → unset,
  `docker logs img2text-dev-server-1 | grep -ci kaggle` → **0** (trước đó 60 lần/30 phút, warning
  kaggle 2.2.4 lặp mỗi scheduler tick), `/healthz` 200. Bật lại = bỏ `#` ở dòng 26.
- 2026-11-04 · `deploy-server-1` (prod) **có** `KAGGLE_KERNEL_REF` nhưng 0 dòng log kaggle →
  chưa từng import kaggle (không có job queued). Sẽ tự gọi lại khi có job queued.
- 2026-11-04 · **Đã implement + smoke PASS trên Kaggle** (`jhandf/img2text-bench-session-smoke`):
  `install_parent_deps()` tách khỏi `bootstrap_venv` (uv có sẵn → bỏ `pip install uv`),
  `_bootstrap_venv_packages` chạy trong thread ∥ `prewarm_rembg` (u2net), `page_rgba()`
  (rembg 1 lần/trang) + `extract_crops(rgba_pages=…)` cắt RGBA theo bbox.
  Số đo code thật: parent deps 39,25 s · song song 251,5 s (0 error) · page_rgba 29,36 s
  (RGBA 1524×1368) · **extract_crops 0,268 s** (trước ~25 s/vùng) · crop 914×820 RGBA alpha 0–255.
  Test: `server/tests` **961 passed** (thêm 4 test: rgba cut, page_rgba None, ensure_uv skip, session cache).
  CHƯA verify: session loop e2e với API thật (claim → job → upload).
- 2026-11-04 · **E2E session kernel PASS** (job 84, PDF tự dựng có text + ảnh nhúng): done 149,65 s,
  34 regions, exports md-layout 7.726B + docx-layout 41.030B. Log kernel xác nhận
  `rembg u2net sẵn sàng` xuất hiện TRƯỚC job (prewarm chạy trong lúc cài venv) và
  `rembg cả trang 1 xong`. Các job PNG 70-byte (test cũ 2026-11-03) fail
  `broken data stream` — input hỏng sẵn, không phải regression; PDF trắng (0 region) cũng OK.
- 2026-11-04 · Bug tự gây ra khi làm prewarm: `prewarm_rembg` gọi `kb.VENV_PY` khi venv chưa tồn tại
  → `FileNotFoundError` → bỏ luôn prewarm ở run 255. Đã sửa (chỉ dùng kernel python), run 256 xác nhận.
- 2026-11-04 · **Commit `9e262e7`** `perf(worker): cold start song song + rembg 1 lần/trang`
  (kernel batch/session + 4 test + `deploy/kaggle/bench/` + MEMORY). E2E gate đã pass trước khi commit.
- 2026-11-04 · Dọn sau e2e: comment lại `KAGGLE_KERNEL_REF` trong `deploy/.env.dev`, recreate dev
  server (kaggle unset, `:8010` healthz 200), kill cloudflared tunnel.
- 2026-11-04 · **UI: edit layout thành MÀN RIÊNG** theo yêu cầu user (preview giữ toggle, edit không nằm
  trong khung preview): route `/jobs/:id/edit` (+ `/edit/md`, `/edit/word`), `btn-edit-doc` = điều hướng
  (Edit → `/edit/<mode>`, Done → `/layout/<mode>`), `switch-mode-*` trong editor → `/edit/<mode>`.
  `/jobs/:id/layout` còn read-only preview.
- 2026-11-04 · **Kích thước nút header đồng nhất 32px** (trước: edit 30, download 40, history 28,
  original 28, zen 24, ⋯ 36) — pin `h-8` ở call site, KHÔNG sửa `Button.SIZES` (thử `h-8` global
  làm 1 test JobDetail treo >300 s; revert). Đo lại bằng Playwright: cả 6 nút = 32.
- 2026-11-04 · `scripts/audit-a11y.mjs` thêm `SHOT_BASE` + `SHOT_ROUTES` (mặc định giữ nguyên 5173 +
  8 route cũ). Chạy với vite :5273 + user `ui-demo` → **DONE 0 routes with findings** (gồm /jobs/84/layout
  và /jobs/84/edit).
- 2026-11-04 · `web/vite.config.ts` thêm `server.allowedHosts` (`.ts.net`, IP tailscale) để xem dev qua
  Tailscale; dev server phụ chạy ở `:5273` (`npx vite --port 5273 --host 0.0.0.0`), 5173/5174 là của
  phiên khác.
- 2026-11-04 · `.git/index.lock` 0 byte còn sót từ lệnh bị kill lúc 12:20 → đã xoá để commit được.
- 2026-11-04 · **Overview job đổi thứ tự ưu tiên**: cột trái = "Kết quả" (MarkdownPreview trong iframe
  tự theme dark/light) + nút Edit/Layout ngay trên đầu; rail phải = link Text, stats, Info (mở sẵn),
  File gốc (**mặc định thu gọn**). Trước đây panel file gốc render trắng chiếm 2/3 trang.
- 2026-11-04 · **Editor kiểu soạn văn bản**: 1 "tờ giấy" canh giữa (max-w 960), toolbar token app,
  pane nhãn SOURCE/PREVIEW, preview là tuỳ chọn (`btn-toggle-preview`, mặc định tắt), Save ở thanh trên.
  CSS mới `web/src/styles/editor-surface.css`. Bài học: KHÔNG padding riêng `.w-md-editor-text-pre`
  và `.w-md-editor-text-input` (2 lớp chồng khít → chữ vẽ đè); padding phải đặt trên container
  `.w-md-editor-text`. Ẩn preview <768px.
