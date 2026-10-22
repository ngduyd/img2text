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

class TestSpecIR:
    """IR từ layout_spec (LLM đã bỏ khỏi bước IR)."""

    def test_one_node_per_region_and_coverage_passes(self):
        from app.services.ir import spec_ir, validate_ir
        result = {"pages": [{
            "index": 0, "width": 800, "height": 1100,
            "regions": [
                {"id": "r0", "bbox": [60, 50, 700, 90], "text": "BÀI 1: GIA ĐÌNH"},
                {"id": "r1", "bbox": [60, 120, 700, 160], "text": "Nội dung đoạn văn."},
                {"id": "r2", "bbox": [60, 200, 300, 240], "text": "Họ tên: ....."},
                {"id": "r3", "bbox": [400, 200, 700, 240], "text": "Ngày: ....."},
            ],
        }]}
        doc = spec_ir(result)
        ids = [i for n in doc["pages"][0]["content"] for i in n["source_block_ids"]]
        assert sorted(ids) == ["r0", "r1", "r2", "r3"], ids   # không mất region
        validate_ir(doc, result)                              # coverage hợp lệ

    def test_types_come_from_layout_spec(self):
        from app.services.ir import spec_ir
        result = {"pages": [{
            "index": 0, "width": 800, "height": 1100,
            "regions": [
                {"id": "r0", "bbox": [60, 50, 700, 90], "text": "BÀI 1: GIA ĐÌNH"},
                {"id": "r1", "bbox": [60, 120, 700, 160], "text": "Nội dung đoạn văn."},
            ],
        }]}
        types = [n["type"] for n in spec_ir(result)["pages"][0]["content"]]
        allowed = {t.value for t in NodeType}
        assert types and set(types) <= allowed, types   # type do layout_spec quyết

    def test_deterministic_same_input_same_output(self):
        from app.services.ir import spec_ir
        result = {"pages": [{"index": 0, "width": 800, "height": 1100,
                             "regions": [{"id": "r0", "bbox": [0, 0, 50, 20],
                                          "text": "x"}]}]}
        assert spec_ir(result) == spec_ir(result)

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
