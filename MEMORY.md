# MEMORY

## Now
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
- 2026-11-04 · Review UI dừng ở mức tài liệu, không sửa code · constraint của task; mọi finding
  phải có `file:line` đọc trực tiếp, số liệu từ MEMORY.md cũ phải đánh dấu "chưa xác minh lại".
- 2026-11-03 · Tắt agentmemory bằng project override `.pi/mcp.json` thay vì sửa `~/.pi/agent/mcp.json`
  · chỉ ảnh hưởng repo này, bật lại bằng cách đổi `enabled: true` hoặc xoá file.
- 2026-11-03 · Thêm `typescript` vào `.serena/project.yml` (trước chỉ `python`) · web/ có 144 file
  .ts/.tsx, thiếu TS server thì serena mù nửa repo; đã verify `get_symbols_overview` trên
  `web/src/api/types.ts` chạy được.

## Measured
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
