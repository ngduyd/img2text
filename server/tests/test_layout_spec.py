"""layout_spec tests: result (bbox px) → PageSpec tất định (không LLM)."""

import json
from pathlib import Path

import pytest

from app.services.layout_spec import build_page_specs

SAMPLES = Path(__file__).parent / "fixtures" / "layout_samples"


def _load(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def one_col():
    return build_page_specs(_load("1col"))[0]


@pytest.fixture(scope="module")
def two_col():
    return build_page_specs(_load("2col"))[0]


@pytest.fixture(scope="module")
def form():
    return build_page_specs(_load("form"))[0]


def _by_id(page):
    return {b.region_id: b for b in page.blocks}


class TestOneColumn:
    def test_single_column_spanning_margins(self, one_col):
        assert len(one_col.cols) == 1
        assert one_col.cols[0].x0 == 80 and one_col.cols[0].x1 == 720
        assert one_col.margin_left == 80

    def test_align_center_when_symmetric_gap(self, one_col):
        assert _by_id(one_col)["r1"].align == "center"

    def test_align_right_when_flush_right(self, one_col):
        assert _by_id(one_col)["r3"].align == "right"

    def test_left_block_has_no_indent(self, one_col):
        assert _by_id(one_col)["r0"].align == "left"
        assert _by_id(one_col)["r0"].indent_px == 0

    def test_image_region_kept_as_image_block(self, one_col):
        img = _by_id(one_col)["r4"]
        assert img.kind == "image"
        assert img.lines == []          # text rỗng không bịa nội dung

    def test_reading_order_top_to_bottom(self, one_col):
        assert [b.region_id for b in one_col.blocks] == [
            "r0", "r1", "r2", "r3", "r5", "r4",
        ]

    def test_space_after_is_gap_to_next_block(self, one_col):
        assert _by_id(one_col)["r0"].space_after_px == 8    # r1.y0 140 − r0.y1 132
        assert _by_id(one_col)["r4"].space_after_px == 0    # block cuối

    def test_font_is_per_line_estimate(self, one_col):
        assert _by_id(one_col)["r2"].font_px == 30          # 90px / 3 dòng

    def test_big_font_blocks_are_headings(self, one_col):
        b = _by_id(one_col)
        assert (b["r0"].type_label, b["r0"].level) == ("heading", 1)
        assert (b["r1"].type_label, b["r1"].level) == ("heading", 2)
        assert [b[r].type_label for r in ("r2", "r3", "r5")] == ["paragraph"] * 3
        assert b["r4"].type_label == "figure"
        assert b["r0"].kind == "text"      # kind cũ giữ cho renderer


class TestTwoColumns:
    def test_two_column_clusters(self, two_col):
        assert len(two_col.cols) == 2
        assert two_col.cols[0].x0 == 80 and two_col.cols[1].x0 == 420

    def test_blocks_grouped_by_column_then_y(self, two_col):
        assert [b.region_id for b in two_col.blocks] == [
            "l0", "l1", "l2", "r0", "r1", "r2",
        ]
        assert [b.col_index for b in two_col.blocks] == [0, 0, 0, 1, 1, 1]

    def test_indent_relative_to_own_column(self, two_col):
        assert _by_id(two_col)["l1"].indent_px == 20   # 100 − 80
        assert _by_id(two_col)["r0"].indent_px == 0     # 420 − 420

    def test_tab_row_inside_left_column(self, two_col):
        tabbed = _by_id(two_col)["l2"]
        assert len(tabbed.tabs) == 1
        tab = tabbed.tabs[0]
        assert tab.pos_px == 180            # 260 − 80
        assert tab.align == "left"
        assert tab.leader == "dots"         # "....." trong nhãn
        # giá trị nối vào đúng block, không thành block riêng
        assert tabbed.lines == ["Ký tên: .....\tTrần B"]
        assert "l3" not in _by_id(two_col)


class TestForm:
    def test_form_rows_collapse_to_one_column(self, form):
        assert len(form.cols) == 1          # hàng nhãn/giá trị không thành 2 cột

    def test_each_row_gets_dot_tab_stop(self, form):
        assert [len(b.tabs) for b in form.blocks] == [1, 1, 1, 0]
        tabs = [b.tabs[0] for b in form.blocks if b.tabs]
        assert [t.pos_px for t in tabs] == [320, 320, 320]
        assert all(t.leader == "dots" for t in tabs)

    def test_table_region_kept_with_cells(self, form):
        tbl = _by_id(form)["tbl"]
        assert tbl.kind == "table"
        assert tbl.cells and len(tbl.cells) == 3

    def test_block_order_label_then_table(self, form):
        assert [b.region_id for b in form.blocks] == ["f0", "f2", "f4", "tbl"]

    def test_label_value_rows_are_form_field(self, form):
        assert [b.type_label for b in form.blocks] == [
            "form_field", "form_field", "form_field", "table",
        ]

    def test_form_field_merges_pair_into_one_block(self, form):
        rows = [b for b in form.blocks if b.type_label == "form_field"]
        assert len(rows) == 3                       # 3 hàng nhãn+giá trị → 3 block
        assert rows[0].lines == ["Họ và tên: .........\tNguyễn Văn A"]
        assert sum(len(b.tabs) for b in rows) == 3

def _two_col_single_line_result() -> dict:
    """Trang 2 cột text THẬT nhưng mọi block 1 dòng (ảnh scan không tách dòng).

    Đây là case đã hỏng: `_column_defining` trả rỗng → cột bị bỏ → cả trang
    thành 1 cột, các dòng trái/phải bị ghép thành tab trên cùng 1 dòng.
    """
    left = [(39, 111), (37, 157), (32, 204), (26, 249), (23, 295)]
    right = [(727, 128), (726, 173), (725, 217), (724, 262), (724, 308)]
    regions = [
        {"id": "h", "bbox": [26, 11, 303, 56], "text": "BAI DOC HAI COT",
         "verdict": "ok", "placeholder": False}
    ]
    for i, (x, y) in enumerate(left):
        regions.append({"id": f"l{i}", "bbox": [x, y, x + 287, y + 46],
                        "text": f"Cot trai dong {i}.", "verdict": "ok", "placeholder": False})
    for i, (x, y) in enumerate(right):
        regions.append({"id": f"r{i}", "bbox": [x, y, x + 275, y + 36],
                        "text": f"Cot phai dong {i}.", "verdict": "ok", "placeholder": False})
    return {"pages": [{"index": 0, "width": 1240, "height": 1754,
                       "page_flag": "ok", "markdown": "", "regions": regions}]}


def test_two_columns_single_line_blocks_are_columns_not_tabs():
    from app.services.layout_spec import build_page_specs

    page = build_page_specs(_two_col_single_line_result())[0]
    assert len(page.cols) == 2, [c for c in page.cols]
    assert not any(b.tabs for b in page.blocks)      # không ghép thành tab
    assert [b.col_index for b in page.blocks].count(1) == 5   # 5 block cột phải


def test_thin_column_singleton_dropped_on_text_page():
    """Header canh giữa + số trang canh phải không được thành cột thứ 2-3."""
    from app.services.layout_spec import build_page_specs

    body = [{"id": f"b{i}", "bbox": [60, 120 + i * 70, 700, 170 + i * 70],
             "text": f"Đoạn văn số {i} nội dung dài bình thường.", "verdict": "ok",
             "placeholder": False} for i in range(4)]
    regions = [{"id": "num", "bbox": [740, 20, 780, 50], "text": "3",
                "verdict": "ok", "placeholder": False}] + body
    page = build_page_specs({"pages": [{"index": 0, "width": 800, "height": 1000,
                                        "page_flag": "ok", "markdown": "",
                                        "regions": regions}]})[0]
    assert len(page.cols) == 1

def test_two_side_header_pair_gets_right_tab():
    """Header 2 bên (BỘ GIÁO DỤC ... | KỲ THI ...) → tab RIGHT tại x1 của khối
    phải, không phải tab LEFT giữa dòng (mất vị trí 2 bên như bản gốc)."""
    from app.services.layout_spec import build_page_specs

    regions = [
        {"id": "l", "bbox": [64, 36, 241, 63], "text": "BỘ GIÁO DỤC VÀ ĐÀO TẠO",
         "verdict": "ok", "placeholder": False},
        {"id": "r", "bbox": [293, 43, 559, 95], "text": "KỸ THI CHỌN HỌC SINH GIỎI",
         "verdict": "ok", "placeholder": False},
        {"id": "body", "bbox": [48, 186, 592, 266], "text": "Nội dung đoạn văn dài.",
         "verdict": "ok", "placeholder": False},
    ]
    page = build_page_specs({"pages": [{"index": 0, "width": 640, "height": 906,
                                        "page_flag": "ok", "markdown": "",
                                        "regions": regions}]})[0]
    block = next(b for b in page.blocks if b.region_id in ("l", "r"))
    assert len(block.tabs) == 1
    tab = block.tabs[0]
    assert tab.align == "right"
    assert tab.pos_px > 0

class TestGenericFixes:
    """Các lỗi gặp trên đề thi thật (job 37) — phải tự xử lý, không sửa tay."""

    def _page(self, regions, w=640, h=906):
        from app.services.layout_spec import build_page_specs
        return build_page_specs({"pages": [{"index": 0, "width": w, "height": h,
                                            "page_flag": "ok", "markdown": "",
                                            "regions": regions}]})[0]

    def test_long_block_is_not_heading(self):
        p = self._page([
            {"id": "a", "bbox": [46, 200, 590, 236], "verdict": "ok",
             "text": "Cho: H = 1,0; Li = 6,9; C = 12,0; N = 14,0; O = 16,0; " * 3},
            {"id": "b", "bbox": [46, 300, 590, 330], "verdict": "ok",
             "text": "Thân bài bình thường."},
        ])
        assert next(b for b in p.blocks if b.region_id == "a").type_label == "paragraph"

    def test_figure_caption_not_tabbed_into_left_paragraph(self):
        p = self._page([
            {"id": "fig", "bbox": [345, 518, 583, 713], "verdict": "image_unextractable",
             "placeholder": True, "text": ""},
            {"id": "left", "bbox": [42, 714, 332, 761], "verdict": "ok",
             "text": "3. Ngoài CO2, một số khí khác cũng gây nên hiệu ứng nhà kính"},
            {"id": "cap", "bbox": [345, 716, 581, 746], "verdict": "ok",
             "text": "Hình 1.1: Giản đồ MO của CO2; các mức năng lượng tương ứng"},
        ])
        by = {b.region_id: b for b in p.blocks}
        assert by["left"].tabs == []
        assert by["cap"].tabs == []
        assert by["cap"].align == "left"

    def test_math_delims_and_latex_simplified(self):
        p = self._page([
            {"id": "f", "bbox": [283, 381, 348, 417], "verdict": "ok",
             "text": " $$ E_{n}=\\frac{n^{2}h^{2}}{8m_{e}L^{2}} $$ "},
            {"id": "t", "bbox": [46, 420, 590, 450], "verdict": "ok",
             "text": "Giá 5$ không bị cắt."},
        ])
        by = {b.region_id: b for b in p.blocks}
        assert by["f"].text == "E_n=n^2h^2/8m_eL^2"
        assert by["t"].text == "Giá 5$ không bị cắt."

    def test_tiny_indent_is_snapped_to_zero(self):
        p = self._page([
            {"id": "body", "bbox": [46, 100, 590, 200], "verdict": "ok",
             "text": "Dòng thân 1.\nDòng thân 2."},
            {"id": "noise", "bbox": [62, 300, 520, 330], "verdict": "ok",
             "text": "Dòng bị OCR lệch 16px."},
        ])
        assert next(b for b in p.blocks if b.region_id == "noise").indent_px == 0.0

def test_formula_block_keeps_latex_and_detex_text():
    page = TestGenericFixes()._page([
        {"id": "f", "bbox": [283, 381, 348, 417], "verdict": "ok",
         "text": " $$ E_{n}=\\frac{n^{2}h^{2}}{8m_{e}L^{2}} $$ "},
    ])
    blk = page.blocks[0]
    assert blk.latex == "E_{n}=\\frac{n^{2}h^{2}}{8m_{e}L^{2}}"
    assert blk.text == "E_n=n^2h^2/8m_eL^2"          # fallback text
    assert blk.lines == ["E_n=n^2h^2/8m_eL^2"]

def test_tab_merge_keeps_line_breaks_of_merged_block():
    """Block phải 4 dòng (Môn/Thời gian/Ngày thi/Đề thi gồm) bị gộp tab:
    trước đây nối bằng ' ' → mất 3 dấu xuống dòng có trong OCR."""
    page = TestGenericFixes()._page([
        {"id": "l", "bbox": [85, 107, 224, 126], "verdict": "ok",
         "text": "ĐỀ THI CHÍNH THỨC"},
        {"id": "r", "bbox": [284, 108, 541, 173], "verdict": "ok",
         "text": "Môn: HÓA HỌC\nThời gian: 180 phút\nNgày thi: 25/12/2024\n05 trang"},
    ])
    blk = page.blocks[0]
    assert len(blk.lines) == 4
    assert blk.lines[0] == "ĐỀ THI CHÍNH THỨC\tMôn: HÓA HỌC"
    assert blk.lines[1] == "\tThời gian: 180 phút"
