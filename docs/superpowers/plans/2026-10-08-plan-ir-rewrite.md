# Plan: IR Rewrite (llm_md + llm_docx → render_md + render_docx + ir)

## Goal
Rewrite layout generation: OCR JSON → LLM (space-bunny) → IR → renderer (MD/DOCX).
Replace `llm_md.py` + `llm_docx.py` with `render_md.py` + `render_docx.py` + `ir.py`.

## Schema IR
```json
{
  "document_id": "doc_001",
  "schema_version": "1.0",
  "pages": [
    {
      "page_id": "page_001",
      "page_number": 1,
      "header": [NodeIR],
      "content": [NodeIR],
      "footer": [NodeIR]
    }
  ]
}
```

NodeIR:
```json
{
  "id": "node_001",
  "type": "heading|paragraph|list|poem|table|figure|caption|formula|quote|footnote|page_number|form_field|separator|unknown",
  "role": "document_title|section_heading|running_header|running_footer|...",
  "text": "...",
  "align": "left|center|right|justify|unknown",
  "indent": 0,
  "source_block_ids": ["p1_b5"],
  "children": []
}
```

## Files

### 1. `server/app/services/ir.py` (new)
- Pydantic models: `DocumentIR`, `PageIR`, `NodeIR`
- `validate_ir(ir: dict, ocr_result: dict) -> DocumentIR`:
  - ID unique
  - type hợp lệ
  - source_block_ids tồn tại trong OCR
  - children không vòng lặp
  - page_number hợp lệ

### 2. `server/app/services/render_md.py` (replaces `llm_md.py`)
- `async def build_md(result: dict, use_llm: bool = True) -> str`:
  1. LLM (space-bunny) → IR JSON
  2. `validate_ir()` → DocumentIR
  3. Render Markdown từ IR:
     - header → 2-col table hoặc plain text
     - content → headings, paragraphs, lists, poems, tables
     - footer → plain text
  4. Fallback: LLM down → heuristic geometry-aware (giữ logic hiện tại)

### 3. `server/app/services/render_docx.py` (replaces `llm_docx.py`)
- `async def build_docx(result: dict, use_llm: bool = True) -> bytes`:
  1. LLM (space-bunny) → IR JSON
  2. `validate_ir()` → DocumentIR
  3. Render DOCX từ IR (python-docx):
     - header → table
     - content → paragraphs, headings, tables
     - footer → table
  4. Fallback: LLM down → heuristic geometry-aware

### 4. `server/app/core/models.py`
- Thêm `jobs.ir_json` TEXT column

### 5. `server/app/services/job_results.py`
- `auto_generate_output()`: gọi `build_md()` + `build_docx()` → lưu IR vào `jobs.ir_json`

### 6. `server/app/routers/jobs.py`
- Export endpoints: đọc IR từ `jobs.ir_json` nếu có

## LLM Prompt
```
You are a document structure analyzer. Given OCR output (blocks with bbox, text), 
produce a Document IR following this schema:
{document_id, schema_version, pages: [{page_id, page_number, header, content, footer}]}

Rules:
- header: blocks at top of page (y0 < 15% page height)
- footer: blocks at bottom of page (y0 > 85% page height)
- content: everything else
- type: heading, paragraph, list, poem, table, figure, caption, formula, quote, footnote, page_number, form_field, separator, unknown
- role: document_title, section_heading, running_header, running_footer, question, answer, ...
- source_block_ids: map to OCR block IDs (p1_b0, p1_b1, ...)
- children: for tables, lists, poems (group related blocks)

OCR output:
{ocr_json}
```

## Fallback (LLM down)
Giữ logic geometry-aware hiện tại:
- `_build_bands()` → `_cluster_columns()` → `_render_band()`
- `_indent_of()` + `_same_cluster()` (vừa thêm)

## Tests
- `tests/test_ir.py`: validator tests (ID unique, type hợp lệ, source_block_ids tồn tại)
- `tests/test_render_md.py`: render MD từ IR
- `tests/test_render_docx.py`: render DOCX từ IR
- Update `tests/test_export_md_layout.py` → dùng `render_md.build_md()`
- Update `tests/test_output_format.py` → dùng `render_md.build_md()` + `render_docx.build_docx()`

## Migration
```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ir_json TEXT;
```

## Verification
1. Test IR validator với job 1 result
2. Test render MD từ IR → so sánh với output hiện tại
3. Test render DOCX từ IR → mở bằng python-docx
4. Test fallback (LLM down) → geometry-aware
5. Full test suite green
