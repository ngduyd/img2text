# Spec: Layout renderer — MD (spacing) + DOCX (style) từ geometry, bỏ LLM render

Date: 2026-10-20
Status: draft — chờ duyệt (user đã chốt: MD best-effort, DOCX phải đúng, KHÔNG framePr/textbox)
Path: bounded — thay tầng render, giữ IR generation

## Problem

Hệ thống hiện tại: OCR (PaddleOCR-VL, worker/Kaggle) → `DocumentIR` (1 LLM call/trang) → **LLM render lần 2** → md hoặc HTML→docx → pandoc.

Đo được (log `img2text.log`): 54/54 LLM call fail → 100% artifact thực tế do heuristic geometry sinh. LLM render không đóng góp gì, và khi chạy được thì:
- md: `figure → [figure: text]` → **mất ảnh**
- không giữ được center/right, indent chỉ là `"\t" * band.indent`
- output không validate (chỉ check rỗng / có tag block)

Thiếu về cấu trúc:
- **MD**: center/right mất; indent thô bằng tab; 2 cột render bằng `_render_columns` nhưng không có quy ước space
- **DOCX**: `html_to_docx` giữ `text-align`, `font-size`, `font-family`, list, table nhưng **không indent, không tab stop, không cột**
- `NodeIR` không có font-size/bold/line-level → dù sửa LLM render cũng không thể render đúng

## Intent

1. **Bỏ LLM render lần 2** (`llm_render_md`, `llm_render_docx`, 2 prompt) — xoá code, không thay bằng call khác.
2. **Layout spec tất định** tính từ bbox OCR: align, indent, tabs, columns, spacing, font-size. Không LLM.
3. **MD = kênh "cấu trúc mức text"**: heading, thụt lề bằng space, verse newline, bảng markdown, ảnh crop. Center: pad bằng space (chấp nhận sai số) — đây là giới hạn của md, ghi rõ trong doc.
4. **DOCX = kênh "layout đúng"**: `w:ind`, `w:tabs`, `w:cols` + continuous section, table, spacing từ bbox.
5. **Không `w:framePr`, không textbox/shape** — mọi block nằm trong dòng chảy paragraph (user chốt). Hệ quả chấp nhận: chữ ký/watermark/block ngoài lề sẽ trôi dòng.
6. IR generation **giữ nguyên** (1 call/trang) cho `/api/jobs/{id}/ir` + coverage check + traceability; renderer đọc OCR `result` (như heuristic hiện tại), **không** phụ thuộc IR.

## Layout spec (output của bước derive)

Per node/line, từ `bbox` + page `width/height` + margin:

| field | nguồn |
|---|---|
| `align` | `left/right_gap` so với cột: `center` nếu |left−right| < tol; `right` nếu right_gap < tol; còn lại `left` |
| `indent_twips` | `(x1 − left_margin) × 1440 / dpi` |
| `first_line_indent` | `x1` line đầu vs `x1` các line sau |
| `tabs[]` | x của từng ô/khối rời trong band → `(pos_twips, alignment, leader)`; form field `....` → `WD_TAB_LEADER.DOTS` |
| `cols` | `_cluster_columns` → số cột + width từng cột + khoảng cách |
| `space_after_pt` | `max(0, gap_px − line_h) × 72 / dpi`, cap 24pt |
| `line_spacing` | `line_h_pt / font_pt` |
| `font_pt` | band height → pt, clamp 8–32 (**suy luận**, hiệu chỉnh bằng ảnh mẫu) |

## Renderer

### MD (`render_md.py`, thay `llm_render_md`)
- indent = `" " × round(x1 / advance)` (advance từ font mono ước lượng), không dùng tab thô
- center → pad trái để cân giữa; right → pad trái đủ
- verse: giữ `_is_verse_pair` (newline đơn)
- 2 cột thật → bảng markdown (`_table_md` sẵn có) hoặc giữ khối tuần tự; ghi rõ giới hạn
- ảnh: `IMAGE_MARKER` → `embed_crop_keys` (đường heuristic sẵn có, đừng bỏ)
- heading: `#` theo `lab["h"]` như hiện tại

### DOCX (`render_docx.py`, thay `llm_render_docx`; không đi qua HTML)
- `paragraph_format.alignment` ← `align`
- `left_indent` ← `Twips(indent_twips)`, `first_line_indent` ← derive
- `tab_stops.add_tab_stop(Twips(pos), WD_TAB_ALIGNMENT.*, leader)` ← `tabs[]`
- cột: gom trang liên tiếp cùng "chữ ký cột" → 1 section; `doc.add_section(WD_SECTION_START.CONTINUOUS)` + `w:cols` (XML thủ công, python-docx không có API)
- band trải hết chiều ngang → section 1 cột
- fallback an toàn: section count > 8 → linearize 1 cột (tránh file vụn)
- bảng thật → table (giữ logic `html_to_docx._table`)
- `space_after` + `line_spacing` ← spec; `space_before = 0` toàn cục (Word cộng cả hai)

### Không đổi
`ir.py` (validate/coverage), `layout_sync.py` (incremental 0-LLM), `embed_crop_*`, `exports.py` pandoc cho plain-md/PDF, `job_results._auto_output`.

## Non-goals

- Không thêm dependency (không MinerU/Docling)
- Không `w:framePr` / textbox / shape
- Không đổi schema IR (không thêm font-size/bold vào NodeIR — renderer lấy từ OCR bbox)
- Không đụng worker/Kaggle, không đổi shape `result`
- Không pixel-perfect: mục tiêu "đúng cấu trúc" (cột, thứ tự, thụt lề, căn lề), không phải bản sao hình học

## Testing

1. **Xoá LLM render**: `build_md`/`build_docx` không còn gọi `_chat`; prompt không còn trong file (assert `not hasattr`).
2. **Layout spec unit test** (deterministic, không cần LLM): bbox tổng hợp → assert `align/indent_twips/tabs/cols/space_after`.
3. **MD regression**: đoạn 2 cột, verse, bảng, ảnh → snapshot md (thứ tự dòng + thụt lề + `![vùng ...]`).
4. **DOCX regression**: 3 tài liệu mẫu (1 cột; 2 cột; trang trộn 1+2 cột) → mở bằng python-docx: assert số section, `w:cols w:num`, `left_indent`, tab stops; assert text order == expected (so `[p.text for p in doc.paragraphs]`).
5. **Reading order**: snapshot text qua `pandoc -f docx -t markdown` cho 3 mẫu → fail nếu thứ tự đổi.
6. **Health check**: `md-layout`/`docx-layout` vẫn qua `auto_generate_output` (≥1 OK → job done) — chạy lại `tests/test_export_md_layout.py`, `test_export_docx.py`, `test_render_docx.py`.

## Files (dự kiến)

- `server/app/services/layout_spec.py` (MỚI: derive spec từ result)
- `server/app/services/render_md.py` (−`RENDER_MD_PROMPT`, −`llm_render_md`, renderer đọc spec)
- `server/app/services/render_docx.py` (−`RENDER_DOCX_PROMPT`, −`llm_render_docx`, render trực tiếp python-docx)
- `server/tests/test_layout_spec.py` (MỚI), `test_render_md.py`, `test_render_docx.py`
- `docs/research-docx-columns.md`, `docs/research-ir-layout.md` (nguồn)

## Rủi ro

- `w:cols` khác nhau giữa Word/LibreOffice (**suy luận**, cần verify bằng mở file thật) → fallback linearize
- mapping font-size/spacing từ pixel là xấp xỉ → hiệu chỉnh bằng 3–5 ảnh mẫu thật
- Bỏ LLM render: nếu heuristic thiếu case (bảng xuyên trang) → không còn đường "LLM cứu"; chấp nhận, vì LLM render chưa từng chạy được
- File docx nhiều section có thể bị Word coi là "phức tạp" khi sửa tay → ưu tiên ít section
