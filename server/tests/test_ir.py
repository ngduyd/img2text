"""IR validator tests: ID unique, type valid, source_block_ids exist, no cycles."""

import json

import pytest

from app.services.ir import (
    DocumentIR,
    NodeIR,
    NodeType,
    PageIR,
    IRValidationError,
    validate_ir,
)


def _ocr_result() -> dict:
    """Minimal OCR result with known block IDs."""
    return {
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "regions": [
                    {"id": "r0", "bbox": [1, 2, 30, 40], "text": "Hello"},
                    {"id": "r1", "bbox": [5, 6, 70, 80], "text": "World"},
                ],
            }
        ]
    }


def _valid_ir() -> dict:
    return {
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [
            {
                "page_id": "page_001",
                "page_number": 1,
                "header": [
                    {
                        "id": "node_001",
                        "type": "paragraph",
                        "role": "running_header",
                        "text": "Header text",
                        "align": "left",
                        "indent": 0,
                        "source_block_ids": ["r0"],
                        "children": [],
                    }
                ],
                "content": [
                    {
                        "id": "node_002",
                        "type": "heading",
                        "role": "section_heading",
                        "text": "Hello",
                        "align": "left",
                        "indent": 0,
                        "source_block_ids": ["r1"],
                        "children": [],
                    }
                ],
                "footer": [],
            }
        ],
    }


class TestValidateIR:
    def test_valid_ir_passes(self):
        ir = validate_ir(_valid_ir(), _ocr_result())
        assert isinstance(ir, DocumentIR)
        assert ir.document_id == "doc_001"
        assert len(ir.pages) == 1
        assert ir.pages[0].page_number == 1

    def test_duplicate_id_rejected(self):
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["id"] = "node_001"  # duplicate
        with pytest.raises(IRValidationError, match="unique"):
            validate_ir(ir, _ocr_result())

    def test_invalid_type_sanitized_to_unknown(self, caplog):
        """Lane IR-NOTE: LLM bịa type lạ ('note', dev job5) → sanitize
        'unknown' + warning, IR hợp lệ (trước: IRValidationError →
        heuristic fallback → ir_json NULL)."""
        caplog.set_level("WARNING", logger="app.services.ir")
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["type"] = "note"
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].type == "unknown"
        assert any("note" in r.getMessage() for r in caplog.records)

    def test_non_dict_input_raises_validation_error(self):
        """P2 (QA): guard non-dict — raise IRValidationError (caller catch → fallback),
        không AttributeError bypass fallback."""
        with pytest.raises(IRValidationError, match="không phải object"):
            validate_ir("not-a-dict", _ocr_result())

    def test_invalid_type_sanitized_in_children(self, caplog):
        """1 node sai type ở children không kill document — sanitize recursive."""
        caplog.set_level("WARNING", logger="app.services.ir")
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["source_block_ids"] = []  # coverage: r1 do child dùng
        ir["pages"][0]["content"][0]["children"] = [
            {"id": "node_c", "type": "text", "role": "body", "text": "x",
             "align": "left", "indent": 0, "source_block_ids": ["r1"],
             "bbox": [5, 6, 70, 80], "children": []}
        ]
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].children[0].type == "unknown"
        assert any("text" in r.getMessage() for r in caplog.records)

    def test_source_block_ids_must_exist(self):
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["source_block_ids"] = ["nonexistent"]
        with pytest.raises(IRValidationError, match="source_block_ids"):
            validate_ir(ir, _ocr_result())

    def test_missing_ocr_region_rejected(self):
        """P0-B: IR bỏ 1 OCR region → mất chữ im im → raise, nêu id thiếu."""
        ir = _valid_ir()
        ir["pages"][0]["header"][0]["source_block_ids"] = []  # bỏ r0
        with pytest.raises(IRValidationError, match="r0"):
            validate_ir(ir, _ocr_result())

    def test_duplicate_source_id_rejected(self):
        """P0-B: 1 OCR id dùng 2 lần → raise, nêu id trùng."""
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["source_block_ids"] = ["r1", "r0"]
        with pytest.raises(IRValidationError, match="r0"):
            validate_ir(ir, _ocr_result())

    def test_cycle_rejected(self):
        ir = _valid_ir()
        # Create cycle: node_003 → node_004 → node_003
        ir["pages"][0]["header"][0]["children"] = [
            {
                "id": "node_003",
                "type": "paragraph",
                "role": "body",
                "text": "child",
                "align": "left",
                "indent": 0,
                "source_block_ids": ["r0"],
                "children": [
                    {
                        "id": "node_004",
                        "type": "paragraph",
                        "role": "body",
                        "text": "grandchild",
                        "align": "left",
                        "indent": 0,
                        "source_block_ids": ["r0"],
                        "children": [
                            {
                                "id": "node_003",  # cycle back
                                "type": "paragraph",
                                "role": "body",
                                "text": "cycle",
                                "align": "left",
                                "indent": 0,
                                "source_block_ids": ["r0"],
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ]
        with pytest.raises(IRValidationError):
            validate_ir(ir, _ocr_result())

    def test_page_number_must_be_positive(self):
        ir = _valid_ir()
        ir["pages"][0]["page_number"] = 0
        with pytest.raises(IRValidationError, match="page_number"):
            validate_ir(ir, _ocr_result())

    def test_empty_ir_valid(self):
        # coverage: OCR không region nào → IR rỗng là hợp lệ
        ocr = {"pages": [{"index": 0, "width": 800, "height": 600, "regions": []}]}
        ir = {
            "document_id": "doc_002",
            "schema_version": "1.0",
            "pages": [],
        }
        result = validate_ir(ir, ocr)
        assert result.pages == []

    def test_fill_text_from_ocr_when_llm_omits(self):
        """LLM structurize không viết lại text → node.text rỗng. validate_ir
        phải join text từ OCR qua source_block_ids (render cần text thật)."""
        ir = _valid_ir()
        ir["pages"][0]["header"][0]["source_block_ids"] = []  # coverage: r0 do content dùng
        node = ir["pages"][0]["content"][0]
        node["text"] = ""  # LLM bỏ trống
        node["source_block_ids"] = ["r0", "r1"]
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].text == "Hello\nWorld"

    def test_all_valid_types_accepted(self):
        valid_types = [
            "heading", "paragraph", "list", "poem", "table", "figure",
            "caption", "formula", "quote", "footnote", "page_number",
            "form_field", "separator", "unknown",
        ]
        for t in valid_types:
            ir = _valid_ir()
            ir["pages"][0]["content"][0]["type"] = t
            result = validate_ir(ir, _ocr_result())
            assert result.pages[0].content[0].type == t

    def test_bbox_len_4_required(self):
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["bbox"] = [1, 2, 3]
        with pytest.raises(IRValidationError, match="bbox"):
            validate_ir(ir, _ocr_result())

    def test_bbox_valid_passes(self):
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["bbox"] = [1, 2, 30, 40]
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].bbox == [1, 2, 30, 40]

    def test_bbox_auto_union_from_source_ids(self):
        """Thiếu bbox → union từ source_block_ids (x1=min, y1=min, x2=max, y2=max)."""
        ir = _valid_ir()
        ir["pages"][0]["header"][0]["source_block_ids"] = []  # coverage: không trùng r0
        ir["pages"][0]["content"][0]["source_block_ids"] = ["r0", "r1"]
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].bbox == [1, 2, 70, 80]

    def test_bbox_none_when_no_source_ids(self):
        # coverage: cả OCR lẫn IR không region nào → node không source → bbox None
        ocr = {"pages": [{"index": 0, "width": 800, "height": 600, "regions": []}]}
        ir = _valid_ir()
        ir["pages"][0]["header"][0]["source_block_ids"] = []
        ir["pages"][0]["content"][0]["source_block_ids"] = []
        result = validate_ir(ir, ocr)
        assert result.pages[0].content[0].bbox is None

    def test_bbox_children_filled(self):
        ir = _valid_ir()
        # coverage: r0 ở header, r1 ở child (content không dùng lại)
        ir["pages"][0]["content"][0]["source_block_ids"] = []
        ir["pages"][0]["content"][0]["children"] = [
            {
                "id": "node_011",
                "type": "paragraph",
                "role": "body",
                "text": "child",
                "align": "left",
                "indent": 0,
                "source_block_ids": ["r1"],
                "children": [],
            }
        ]
        result = validate_ir(ir, _ocr_result())
        assert result.pages[0].content[0].children[0].bbox == [5, 6, 70, 80]

    def test_children_validated_recursively(self):
        ir = _valid_ir()
        # coverage: r0 ở header, r1 ở child (content không dùng lại)
        ir["pages"][0]["content"][0]["source_block_ids"] = []
        ir["pages"][0]["content"][0]["children"] = [
            {
                "id": "node_010",
                "type": "paragraph",
                "role": "body",
                "text": "child text",
                "align": "left",
                "indent": 0,
                "source_block_ids": ["r1"],
                "children": [],
            }
        ]
        result = validate_ir(ir, _ocr_result())
        assert len(result.pages[0].content[0].children) == 1
        assert result.pages[0].content[0].children[0].id == "node_010"


def _ocr_with_image() -> dict:
    """OCR + 1 image region (verdict marker, text rỗng)."""
    return {
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "regions": [
                    {"id": "r0", "bbox": [1, 2, 30, 40], "text": "Hello"},
                    {"id": "r1", "bbox": [5, 6, 70, 80], "text": "World"},
                    {"id": "r2", "bbox": [5, 90, 70, 150], "text": "",
                     "verdict": "image_unextractable", "placeholder": True},
                ],
            }
        ]
    }

class TestCoverageImageRegion:
    """P1-R4b: LLM KHÔNG bắt buộc cover image region (prompt không đổi);
    text region vẫn bắt buộc."""

    def test_image_region_not_required_in_coverage(self):
        ir = _valid_ir()  # cover r0 + r1, bỏ r2 (image)
        doc = validate_ir(ir, _ocr_with_image())
        assert doc.pages[0]

    def test_text_region_still_required(self):
        ir = _valid_ir()
        ir["pages"][0]["header"][0]["source_block_ids"] = []  # bỏ r0
        with pytest.raises(IRValidationError, match="r0"):
            validate_ir(ir, _ocr_with_image())

    def test_placeholder_without_image_verdict_still_required(self):
        """P2-1: exempt coverage CHỈ khi verdict=image — region placeholder
        nhưng verdict khác (LLM mislabel text→image) vẫn bắt buộc cover,
        không được bỏ qua coverage (mất text im im)."""
        ocr = _ocr_with_image()
        region = ocr["pages"][0]["regions"][2]
        region["verdict"] = "ok"  # mislabel: placeholder nhưng KHÔNG phải image
        ir = _valid_ir()  # cover r0 + r1, bỏ r2
        with pytest.raises(IRValidationError, match="r2"):
            validate_ir(ir, ocr)

    def test_image_region_as_source_id_accepted(self):
        """LLM cover image region → source id hợp lệ (không reject)."""
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["source_block_ids"] = ["r1", "r2"]
        validate_ir(ir, _ocr_with_image())

class TestGeometryFirstPrompt:
    """Wave-4 #8: IR prompt geometry-primary — group theo bbox TRƯỚC, type SAU."""

    def _two_column_prompt(self) -> str:
        """Fixture header 2 cột: b0/b2 trái + b3/b4 phải → build prompt."""
        result = {
            "pages": [{
                "index": 0, "width": 800, "height": 600,
                "regions": [
                    {"id": "b0", "bbox": [10, 10, 380, 40],
                     "text": "TRƯỜNG THPT"},
                    {"id": "b2", "bbox": [10, 50, 380, 80],
                     "text": "ĐỀ THI HỌC KỲ"},
                    {"id": "b3", "bbox": [420, 10, 790, 40],
                     "text": "Môn: Toán"},
                    {"id": "b4", "bbox": [420, 50, 790, 80],
                     "text": "Thời gian: 90 phút"},
                ],
            }]
        }
        import json
        from app.services.ir import IR_PROMPT
        return IR_PROMPT.replace("{ocr_json}", json.dumps(result, ensure_ascii=False))

    def test_prompt_instructs_parallel_columns_by_geometry(self):
        prompt = self._two_column_prompt()
        # pin key phrases của rule geometry-first
        assert "GEOMETRY FIRST" in prompt
        assert "overlapping y-range and disjoint x-range" in prompt
        assert "parallel columns" in prompt
        assert "left" in prompt and "right" in prompt  # đọc trái→phải mỗi hàng
        # fixture đi qua prompt build — đủ 4 block, 2 cột
        for rid in ("b0", "b2", "b3", "b4"):
            assert rid in prompt

    def test_prompt_type_set_and_label_after_geometry(self):
        prompt = self._two_column_prompt()
        assert "type is only used to LABEL the node AFTER geometry grouping" in prompt
        for t in ("heading (level1..N by position/size)", "paragraph", "list",
                  "poem", "table", "figure", "caption", "formula", "quote",
                  "footnote", "page_number", "form_field", "separator"):
            assert t in prompt, t
        # full type set liệt kê đủ unknown (đồng nhất với MUST-line) —
        # pin riêng câu Full type set (MUST-line cũng liệt kê unknown → không pin chung)
        full_set = prompt.split("Full type set: ", 1)[1].split("\n", 1)[0]
        assert "unknown" in full_set, full_set
        # geometry rule cho từng loại
        assert "regular grid" in prompt          # table
        assert "hanging indent" in prompt        # list
        assert "first block of a band = heading" in prompt
        assert "image blocks = figure nodes" in prompt


# --- Lane S Task 4: extract_heading_anchors (S3) ---

from app.services.ir import (
    IR_PROMPT, IR_PROMPT_PAGE, AnchorState, extract_heading_anchors,
)

def _page(regions: list, height: int = 1000) -> dict:
    return {"index": 0, "width": 800, "height": height, "regions": regions}

def _blk(rid: str, text: str, y0: int) -> dict:
    return {"id": rid, "bbox": [10, y0, 300, y0 + 30], "text": text,
            "verdict": "ok", "placeholder": False}

def _headings(anns: list) -> list:
    return [a for a in anns if a["type"] == "heading"]

def test_heading_anchor_positive_matrix():
    texts = ["1. Benefit", "1) Foo", "1.1.1 Sub", "   2.2 Indent"]
    regions = [_blk(f"r{i}", t, 100 + i * 50) for i, t in enumerate(texts)]
    anns, _ = extract_heading_anchors([_page(regions)])
    ids = {a["block_id"] for a in _headings(anns)}
    assert ids == {"r0", "r1", "r2", "r3"}, anns

def test_heading_anchor_negative_matrix():
    # 4-digit năm, không có [.)]+space, không đầu block
    texts = ["2024. Năm", "Câu 1:", "Bài 2", "abc 1. x", "1)Foo"]
    regions = [_blk(f"r{i}", t, 100 + i * 50) for i, t in enumerate(texts)]
    anns, _ = extract_heading_anchors([_page(regions)])
    assert _headings(anns) == [], anns

def test_heading_anchor_level_from_numbering():
    regions = [_blk("r0", "1. A", 100), _blk("r1", "1.1.1 Deep", 200)]
    anns, _ = extract_heading_anchors([_page(regions)])
    by_id = {a["block_id"]: a for a in _headings(anns)}
    assert by_id["r0"]["level"] == 1
    assert by_id["r1"]["level"] == 3

def test_heading_anchor_sequence_continuous_across_pages():
    """State carry: §numbering liên tục xuyên trang, KHÔNG reset."""
    p1 = _page([_blk("r0", "1. Mục một", 100), _blk("r1", "1.1 Gốc con", 300)])
    p2 = _page([_blk("r2", "2. Mục hai", 100), _blk("r3", "1) Mục ba", 300)])
    p2["index"] = 1
    anns1, st = extract_heading_anchors([p1], None)
    anns2, st = extract_heading_anchors([p2], st)
    labels = [a["label"] for a in _headings(anns1 + anns2)]
    assert labels == ["§1", "§1.1", "§2", "§3"], labels

def test_heading_anchor_header_yband_15pct_excluded():
    """Top 15% y-band + không số → header/doc_title, KHÔNG tham gia §index."""
    regions = [
        _blk("t0", "TRƯỜNG THCS ABC", 20),      # y=20 < 150 = 15%*1000
        _blk("t1", "Kỳ thi học kỳ I", 60),
        _blk("r0", "1. Benefit", 400),
    ]
    anns, _ = extract_heading_anchors([_page(regions)])
    types = {a["block_id"]: a["type"] for a in anns}
    assert types["t0"] == "doc_title"
    assert types["t1"] == "header"
    assert types["r0"] == "heading"
    assert all("label" not in a for a in anns if a["block_id"].startswith("t"))
    # y-band 15%: block dưới 150px vẫn là heading bình thường
    low = [_blk("r9", "2. Dưới", 200)]
    anns2, _ = extract_heading_anchors([_page(low)])
    assert [a["type"] for a in anns2] == ["heading"]


# --- Lane S Task 5: _ir_page sequential shared (S2) ---

from app.services import ir as ir_mod
from app.services.ir import IRPageError, MAX_IR_PAGE_CALLS, _ir_page, llm_ir_pages

def _one_page_result(n: int = 1) -> dict:
    return {
        "pages": [
            {"index": i, "width": 800, "height": 600,
             "regions": [{"id": f"p{i}_b0", "bbox": [10, 100, 300, 130],
                          "text": f"1. Trang {i} nội dung", "verdict": "ok",
                          "placeholder": False}]}
            for i in range(n)
        ]
    }

def _page_ir(page_number: int, bid: str) -> dict:
    return {
        "page_id": f"page_{page_number:03d}",
        "page_number": page_number,
        "header": [],
        "content": [{"id": f"node_{page_number}", "type": "paragraph",
                     "role": "body", "text": f"Trang {page_number}",
                     "align": "left", "indent": 0, "source_block_ids": [bid],
                     "bbox": [10, 100, 300, 130], "children": []}],
        "footer": [],
    }

async def test_ir_pages_sequential_order_and_context():
    """2 page → đúng 2 call đúng thứ tự; page2 prompt chứa §context page1;
    merge sort page_number, map page_id đúng trang."""
    result = _one_page_result(2)
    calls: list = []
    async def chat(content: str) -> str:
        calls.append(content)
        n = len(calls)
        return json.dumps(_page_ir(n, f"p{n-1}_b0"))
    doc = await llm_ir_pages(result, chat)
    assert len(calls) == 2, calls
    # page1 prompt không có §context; page2 prompt chứa heading §context page1
    assert "§1" not in calls[0]
    assert "§1" in calls[1]
    pages = sorted(doc["pages"], key=lambda p: p["page_number"])
    assert [p["page_number"] for p in pages] == [1, 2]
    assert [p["page_id"] for p in pages] == ["page_001", "page_002"]
    assert pages[0]["content"][0]["source_block_ids"] == ["p0_b0"]
    assert pages[1]["content"][0]["source_block_ids"] == ["p1_b0"]

async def test_ir_pages_degrade_full_when_over_cap():
    """> MAX_IR_PAGE_CALLS → degrade 1-call full-result (legacy IR_PROMPT)."""
    result = _one_page_result(MAX_IR_PAGE_CALLS + 1)
    calls: list = []
    async def chat(content: str) -> str:
        calls.append(content)
        return json.dumps({"document_id": "d", "schema_version": "1.0",
                           "pages": [_page_ir(1, "p0_b0")]})
    doc = await llm_ir_pages(result, chat)
    assert len(calls) == 1
    assert f'"index": {MAX_IR_PAGE_CALLS}' in calls[0]  # full-result, không per-page
    assert doc["pages"]

async def test_ir_pages_page_fail_retry_then_fallback_full():
    """Page fail → retry 1 → still fail → fallback legacy IR_PROMPT 1-call."""
    result = _one_page_result(2)
    calls: list = []
    async def chat(content: str) -> str:
        calls.append(content)
        if len(calls) <= 2:  # page1 attempt 1 + retry đều fail
            raise RuntimeError("LLM 5xx")
        return json.dumps({"document_id": "d", "schema_version": "1.0",
                           "pages": [_page_ir(i + 1, f"p{i}_b0") for i in range(2)]})
    doc = await llm_ir_pages(result, chat)
    assert len(calls) == 3  # 2 fail + 1 full fallback
    assert [p["page_number"] for p in doc["pages"]] == [1, 2]

async def test_ir_pages_duplicate_pagenumber_raises():
    """Merge check: page_number trùng → IRPageError (→ LLMError → heuristic)."""
    result = _one_page_result(2)
    calls: list = []
    async def chat(content: str) -> str:
        calls.append(content)
        return json.dumps(_page_ir(1, f"p{len(calls)-1}_b0"))  # cả 2 page_number=1
    with pytest.raises(IRPageError):
        await llm_ir_pages(result, chat)

async def test_ir_page_prompt_shape():
    """_ir_page: prompt = IR_PROMPT_PAGE chứa running_ctx + OCR json trang."""
    seen: list = []
    async def chat(content: str) -> str:
        seen.append(content)
        return json.dumps(_page_ir(1, "p0_b0"))
    page_ir = await _ir_page(_one_page_result()["pages"][0], "§1 Tiêu đề", chat)
    assert page_ir["page_number"] == 1
    assert "§1 Tiêu đề" in seen[0]
    assert "p0_b0" in seen[0]

async def test_render_modules_delegate_shared_ir(monkeypatch):
    """render_md.llm_ir + render_docx.llm_ir dùng chung llm_ir_pages (1 logic)."""
    import app.services.render_docx as rd
    import app.services.render_md as rm
    fake_doc = {"document_id": "d", "schema_version": "1.0", "pages": []}
    seen = {}
    async def fake_pages(result, chat_fn):
        seen["chat"] = chat_fn
        return fake_doc
    monkeypatch.setattr(rm, "llm_ir_pages", fake_pages)
    monkeypatch.setattr(rd, "llm_ir_pages", fake_pages)
    assert await rm.llm_ir({"pages": []}) is fake_doc
    assert await rd.llm_ir({"pages": []}) is fake_doc


# --- Lane S Task 6: prompt rules (S4/S3) + validator warning ---

def test_ir_prompt_page_has_s4_s3_rules():
    """IR_PROMPT_PAGE: cross-column rule + table exception + header y-band
    15% + §anchor instruction."""
    p = IR_PROMPT_PAGE
    assert "y-band" in p.lower() or "y band" in p.lower()
    assert "column" in p.lower()
    assert "table" in p.lower() and "exempt" in p.lower() or "except" in p.lower()
    assert "15%" in p
    assert "§" in p  # §anchor instruction

def test_legacy_ir_prompt_unchanged_snapshot():
    """Legacy IR_PROMPT (degrade path) không đổi — snapshot guard."""
    assert "produce a Document IR following this schema" in IR_PROMPT
    assert "COVERAGE: every OCR block id" in IR_PROMPT
    assert "y0 < 15% page height" in IR_PROMPT
    # IR_PROMPT_PAGE rules KHÔNG lọt vào legacy prompt (degrade path giữ behavior)
    assert "y-band" not in IR_PROMPT
    assert "§" not in IR_PROMPT

def test_prompt_closed_type_set_matches_enum():
    """Lane IR-NOTE: cả IR_PROMPT lẫn IR_PROMPT_PAGE ép closed set —
    list type trong prompt khớp enum NodeType 1-1 (không thiếu/không thừa)."""
    import re
    enum_types = {t.value for t in NodeType}
    for prompt in (IR_PROMPT, IR_PROMPT_PAGE):
        assert "MUST be exactly one of" in prompt
        assert "NEVER invent new types" in prompt
        listed = prompt.split("MUST be exactly one of: ", 1)[1].split(".", 1)[0]
        assert set(re.findall(r"[a-z_]+", listed)) == enum_types, listed
    # negative examples có mặt — LLM hay bịa 'note' (bug dev job5)
    assert "'note'" in IR_PROMPT and "'note'" in IR_PROMPT_PAGE

def _col_ocr(left_type_text: str = "Cột trái đoạn văn", right_text: str = "Cột phải") -> dict:
    """2 cột x-disjoint, cùng y-band: r_left + r_right."""
    return {
        "pages": [
            {
                "index": 0, "width": 800, "height": 600,
                "regions": [
                    {"id": "r_left", "bbox": [10, 100, 350, 160],
                     "text": left_type_text, "verdict": "ok", "placeholder": False},
                    {"id": "r_right", "bbox": [450, 105, 780, 155],
                     "text": right_text, "verdict": "ok", "placeholder": False},
                ],
            }
        ]
    }

def _col_ir(left_type: str, right_type: str) -> dict:
    return {
        "document_id": "d", "schema_version": "1.0",
        "pages": [{
            "page_id": "p1", "page_number": 1, "header": [], "footer": [],
            "content": [
                {"id": "n1", "type": left_type, "role": "body", "text": "a",
                 "align": "left", "indent": 0, "source_block_ids": ["r_left"],
                 "bbox": [10, 100, 350, 160], "children": []},
                {"id": "n2", "type": right_type, "role": "body", "text": "b",
                 "align": "left", "indent": 0, "source_block_ids": ["r_right"],
                 "bbox": [450, 105, 780, 155], "children": []},
            ],
        }],
    }

def test_validate_ir_warns_cross_column_type_mismatch(caplog):
    """Cùng y-band + 2 cột x-disjoint + khác type + không bảng → warning."""
    caplog.set_level("WARNING", logger="app.services.ir")
    doc = validate_ir(_col_ir("heading", "paragraph"), _col_ocr())
    assert doc.pages
    warns = [r.getMessage() for r in caplog.records]
    assert any("cross-column" in w for w in warns), warns

def test_validate_ir_table_exception_no_warning(caplog):
    """Block có <table trong OCR text → ngoại lệ, KHÔNG warn."""
    caplog.set_level("WARNING", logger="app.services.ir")
    ocr = _col_ocr(right_text="<table><tr><td>x</td></tr></table>")
    validate_ir(_col_ir("heading", "table"), ocr)
    assert not any("cross-column" in r.getMessage() for r in caplog.records)

def test_validate_ir_cells_grid_exception_no_warning(caplog):
    """P2-1: region có `cells` grid (không có <table> text) → cũng exempt."""
    caplog.set_level("WARNING", logger="app.services.ir")
    ocr = _col_ocr()
    ocr["pages"][0]["regions"][1]["cells"] = [
        [{"text": "a", "rowspan": 1, "colspan": 1, "header": True}]
    ]
    validate_ir(_col_ir("heading", "table"), ocr)
    assert not any("cross-column" in r.getMessage() for r in caplog.records)

def test_validate_ir_same_type_no_warning(caplog):
    caplog.set_level("WARNING", logger="app.services.ir")
    validate_ir(_col_ir("paragraph", "paragraph"), _col_ocr())
    assert not any("cross-column" in r.getMessage() for r in caplog.records)
