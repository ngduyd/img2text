# RESEARCH — Dựng lại layout: giữ IR+LLM render hay đổi hướng?

Read-only. Không sửa code nguồn. Mỗi khẳng định có nguồn hoặc ghi "suy luận".

## 0. Kết luận
- **Đừng render bằng LLM lần 2.** Toàn bộ hệ sinh thái hiện đại làm: layout model/VLM sinh **markdown/json trực tiếp** từ ảnh/PDF, còn **DOCX/HTML do serializer deterministic** (Docling exporters, MinerU `middle_json`→renderer, pandoc). Không có ai để LLM "viết lại" layout từ IR.
- **Công cụ của project đã dùng VLM sinh markdown ở tầng OCR** (`deploy/kaggle/kernel/img2text_batch.py:57` = `PaddleOCR-VL-1.5-0.9B`, `res_json["markdown"]`). Tầng LLM IR + LLM render phía server **trùng chức năng** với VLM đó, chỉ khác nguồn geometry.
- **IR nên giữ** (nguồn sự thật, coverage check, traceability, heading §anchor) — **bỏ LLM render lần 2**, thay bằng serializer tất định IR→markdown rồi pandoc (đã có sẵn cho nhánh `md`/`docx`).

## 1. Bảng so sánh (license / GPU / VN / output / LLM?)
| Công cụ | License | GPU/VRAM | Tiếng Việt | Output | LLM? |
|---|---|---|---|---|---|
| Docling | MIT (code) | CPU OK; VLM tùy chọn | qua OCR engine | md, html, json, doctags, doclang — **không có docx** | không (pipeline cổ điển); VLM tuỳ chọn |
| Marker | Apache-2.0 code; **OpenRAIL-M weights** | GPU/CPU/MPS | đa ngôn ngữ | md, json, html, chunks | **tuỳ chọn `--use_llm`** (mặc định TẮT) |
| Surya | Apache-2.0 code; OpenRAIL-M weights | GPU/CPU | **91 ngôn ngữ; VN 73.2% (yếu)** | JSON (layout, reading order, html block), table | không |
| MinerU | Apache-2.0 **+ điều khoản bổ sung** | basic 4GB VRAM; standard 8GB+ | đa ngôn ngữ | **9 target: md, html, latex, docx, epub, pdf, structured, content-list v1/v2** | VLM nội bộ (MinerU2.5 1.2B) |
| PaddleOCR PP-StructureV3 | Apache-2.0 | CPU/GPU/XPU | **109 ngôn ngữ (PaddleOCR-VL)**; PP-OCRv6 50 | **md, json, DOCX** (kèm toạ độ ô) | PaddleOCR-VL là VLM; PP-StructureV3 là pipeline |
| olmOCR | Apache-2.0 | **≥12GB VRAM** (7B VLM) | không nêu | markdown | **VLM sinh md** |
| dots.ocr | MIT | GPU/vLLM | đa ngôn ngữ | markdown (+SVG cho chart) | **VLM 1.7B sinh markdown** |
Nguồn: Docling README+`docling-core/.../document.py` (`export_to_markdown/html/text/dict/vtt/doctags/doclang`); Marker README; Surya README+`static/docs/multilingual.md`; MinerU README+LICENSE.md+docs `reference/output_files/`; PaddleOCR README; olmOCR README; dots.ocr README.

## 2. Pattern chuẩn "IR → serializer deterministic"
1. **Docling**: `DoclingDocument` (IR: item, label, bbox, parent) → `export_to_markdown/html/json`. IR tách khỏi exporter; exporter thuần. Ưu: inspectable, deterministic, testable. Nhược: **không export DOCX** → phải pandoc.
2. **MinerU**: `middle.json` (IR có bbox + category) → `mineru.render.render()` ra 9 định dạng, gồm **DOCX**. Ưu: 1 IR nhiều output, DOCX native. Nhược: license có điều khoản bổ sung.
3. **Pandoc** (project đã dùng ở `server/app/routers/exports.py:257-277`): markdown → html/docx/pdf, deterministic, không LLM. Ưu: miễn phí, ổn định. Nhược: layout phẳng, mất cột/indent phức tạp.
4. **LayoutLens** (YouTube 0uIqEbQTrD8): "recognition and reconstruction are kept separate — OCR chỉ trả text + bbox, **spatial grid algorithm** dựng lại layout". Đây chính là kiến trúc project đang có (OCR regions → geometry).

## 3. Ý kiến thực chiến (YouTube)
- **nN6TCvQ7QKs** (9 converter, 5 PDF): "Marker đọc xuyên trang, xen kẽ 2 cột — mọi từ còn nhưng quan hệ sai. Với RAG thì 'ai ký gì' là dữ liệu." → **reading-order là bài toán geometry, không phải LLM**. Docling "giữ khoảng trống trung thực nhưng mất công thức và ảnh".
- **8RxT5jTcemY** (Docling/Marker/MinerU): Marker có "**optional LLM refinement pass** dọn 5% khó (bảng xuyên trang, công thức dày, form)". → LLM chỉ nên là **tầng tinh chỉnh cho case khó**, không phải render chính.
- **KqPR2NIekjI**: Marker "vất vả với trang nhiều cột, đôi khi đặt sai/ bỏ sót nội dung". → layout 2 cột cần geometry, đúng chỗ IR hiện tại lo.
- **0uIqEbQTrD8** (LayoutLens): OCR thường "ném đi geometry; cột và bảng bị dàn phẳng" — xử lý đúng = giữ 2D layout, dựng HTML có cấu trúc.
- **BFxSYP5IRjQ**: tài liệu tài chính có **68% lỗi là số bịa/hallucinate** → LLM không được phép "viết lại" text.

## 4. Đối chiếu pipeline hiện tại
**Đáng giữ**
- `ir.py` coverage check (mọi region exactly-once), unique-id, cycle, source_block_ids, `_fill_text` (không viết lại text) — đúng tinh thần "LLM không rewrite".
- `_warn_cross_column`, `_cluster_columns`, band analysis (`render_md.py`/`render_docx.py`) — geometry heuristic đúng hướng.
- `embed_crop_keys`/`embed_crop_urls` — giữ ảnh/crop (điểm mà LLM md render đang mất: `figure → [figure: text]`).
- §anchor heading, traceability qua source_block_ids.

**Nên bỏ**
- `RENDER_MD_PROMPT`/`RENDER_DOCX_PROMPT` — LLM render lần 2 (đã 100% fail thực tế → heuristic; dù sửa base_url vẫn sai kiến trúc: mất ảnh, mất font, không validate).
- NodeIR không có font-size/bold/line-level → không thể render đúng layout; thêm field là vô nghĩa nếu bỏ LLM render.

**Thiếu**
- Serif/đậm/cỡ chữ, line-level, chú thích ảnh, ảnh crop trong md, validate output (hiện chỉ check tag block).

## 5. Đề xuất
**H1 — IR → serializer tất định (khuyến nghị).** Giữ `validate_ir`; bỏ LLM render; viết 1 hàm IR→markdown (dùng lại `render_md.py::_cells_md`, `_table_md`, band/indent) và 1 hàm IR→HTML; DOCX/PDF qua **pandoc** (đã có) hoặc `python-docx` cho bảng/cột. Công sức: trung bình. Rủi ro: thấp. Tận dụng: ~toàn bộ `ir.py` + heuristic. Điều kiện: cần md/docx đúng cấu trúc, giữ ảnh, không cần "sáng tạo".

**H2 — Chỉ giữ VLM sinh markdown + IR sửa geometry.** Dùng `result["markdown"]` của PaddleOCR-VL làm nền, IR chỉ **ghép nối lại** cột/bảng/verse, không sinh lại text. Công sức: nhỏ. Rủi ro: VLM mất cột (đúng lỗi KqPR2NIekjI) → IR phải đủ mạnh. Điều kiện: chấp nhận markdown từ VLM làm nguồn chính, IR là tầng sửa.

**H3 — Dùng thư viện xuất DOCX native.** Thay `python-docx` bằng MinerU/Docling-docx cho nhánh layout. Công sức: lớn + dependency + rủi ro license (MinerU điều khoản bổ sung). Điều kiện: chỉ khi cần DOCX layout cao cấp và chấp nhận license/ràng buộc VRAM.

## 6. Nguồn
**Docs/repo**
- https://github.com/docling-project/docling (MIT) · https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/document.py
- https://github.com/datalab-to/marker (Apache-2.0/OpenRAIL-M, `--use_llm`) · https://github.com/datalab-to/surya (Apache-2.0/OpenRAIL-M) · https://raw.githubusercontent.com/datalab-to/surya/master/static/docs/multilingual.md
- https://github.com/opendatalab/MinerU · https://github.com/opendatalab/MinerU/blob/master/LICENSE.md · https://opendatalab.github.io/MinerU/reference/output_files/
- https://github.com/PaddlePaddle/PaddleOCR (Apache-2.0; PP-StructureV3 + PaddleOCR-VL; md/json/DOCX)
- https://github.com/allenai/olmocr (Apache-2.0; 7B VLM; ≥12GB) · https://github.com/rednote-hilab/dots.ocr (MIT; 1.7B VLM)
- https://pandoc.org

**YouTube**
- `8RxT5jTcemY` — Docling vs Marker vs MinerU: The Real Open-Source PDF Parser Benchmark (2026) — Tech with Aditya Mangal
- `KqPR2NIekjI` — Docling vs MarkitDown vs Marker - PDF to MarkDown Tool Comparison — Fahd Mirza
- `nN6TCvQ7QKs` — Best PDF-to-Markdown Tools for AI & RAG? I Tested 9 — Free PDF to Markdown Converter
- `BFxSYP5IRjQ` — I Tested 5 Document Parsers for AI Agents — Dr. Maryam Miradi
- `0uIqEbQTrD8` — Stop Losing Document Layouts in OCR | Build Structural HTML with LayoutLens — LetsAI
- `bLyjSpo24ZM` — I Built a Self-Hosted OCR Pipeline That Turns PDFs & Images Into Layout-Preserving DOCX Files — InventaAI (không lấy được phụ đề; chỉ dùng tiêu đề)

## 7. Rủi ro còn lại (gaps)
- Chưa có benchmark cho tiếng Việt, văn 2 cột/thơ/chú thích trên bất kỳ công cụ nào ở trên (surya VN 73.2% là số nội bộ, không tái lập được).
- Docling không export DOCX → H3 cần pandoc.
- License MinerU có điều khoản bổ sung → cần duyệt pháp lý nếu dùng cho thương mại.
- Không đo được tốc độ thực tế trên Kaggle/Colab GPU của project (chưa chạy thử).
