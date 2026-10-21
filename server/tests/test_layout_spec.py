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
