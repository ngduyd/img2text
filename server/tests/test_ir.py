"""IR validator tests: ID unique, type valid, source_block_ids exist, no cycles."""

import pytest

from app.services.ir import (
    DocumentIR,
    NodeIR,
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

    def test_invalid_type_rejected(self):
        ir = _valid_ir()
        ir["pages"][0]["content"][0]["type"] = "invalid_type"
        with pytest.raises(IRValidationError, match="type"):
            validate_ir(ir, _ocr_result())

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
        # geometry rule cho từng loại
        assert "regular grid" in prompt          # table
        assert "hanging indent" in prompt        # list
        assert "first block of a band = heading" in prompt
        assert "image blocks = figure nodes" in prompt
