"""layout_spec: OCR result (bbox px) → layout spec tất định.

Không LLM, không DB, không pydantic — dataclass thuần. Nguồn: spec
`docs/superpowers/specs/2026-10-20-layout-renderer-md-docx-design.md` §4.

Input: result["pages"][*] = {index, width, height,
        regions: [{id, bbox: [x0, y0, x1, y1], text, verdict, html, cells}]}
Output: list[PageSpec] — mỗi block có align/indent/tabs/spacing/font suy từ bbox.
"""

from __future__ import annotations

import logging
import statistics
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger("app.services.layout_spec")

# ---------------------------------------------------------------- constants
X_TOL = 4.0                 # px — 2 block coi như chồng cột
Y_RATIO = 0.5               # tỉ lệ overlap dọc tối thiểu để coi là "cùng hàng"
ALIGN_TOL_RATIO = 0.02      # 2% page width — |left_gap − right_gap| < tol → center
FONT_MIN, FONT_MAX = 10.0, 48.0
FONT_FALLBACK = 16.0
DOTS = "...."               # ≥4 chấm → tab leader DOTS
TAB_SPACE_PX = 8.0          # px ước lượng cho 1 ký tự space khi tính first-line indent

# ---------------------------------------------------------------- dataclasses
@dataclass
class Col:
    x0: float
    x1: float


@dataclass
class Tab:
    pos_px: float
    align: str = "left"
    leader: str = "none"    # "none" | "dots"


@dataclass
class BlockSpec:
    region_id: str
    kind: str               # text | table | image
    text: str
    bbox: tuple
    col_index: int = 0
    align: str = "left"
    indent_px: float = 0.0
    first_line_indent_px: float = 0.0
    tabs: list[Tab] = field(default_factory=list)
    space_after_px: float = 0.0
    font_px: float = FONT_FALLBACK
    html: str = ""
    cells: list | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def w(self) -> float:
        return max(1.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(1.0, self.y1 - self.y0)


@dataclass
class PageSpec:
    width: float
    height: float
    margin_left: float
    cols: list[Col]
    blocks: list[BlockSpec]


# ---------------------------------------------------------------- extract
def _lines_of(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def _kind_of(region: dict, text: str) -> str:
    if region.get("cells") or "<table" in text.lower():
        return "table"
    if region.get("placeholder") or region.get("verdict") == "image_unextractable":
        return "image"
    return "text"


def _extract_regions(page: dict) -> list[BlockSpec]:
    out: list[BlockSpec] = []
    seen: set[str] = set()
    for region in page.get("regions", []):
        text = unicodedata.normalize("NFC", region.get("text") or "")
        kind = _kind_of(region, text)
        bbox_raw = region.get("bbox")
        if not bbox_raw or len(bbox_raw) != 4:
            if kind != "image":       # text thiếu bbox → bỏ; image giữ marker
                continue
            bbox_raw = (0, 0, 0, 0)
        if kind != "image" and not text.strip() and not region.get("cells"):
            continue
        rid = str(region.get("id"))
        while rid in seen:
            rid = f"p{rid}"
        seen.add(rid)
        html = region.get("html") or (text if kind == "table" else "")
        if kind == "table" and html:
            text = html
        out.append(
            BlockSpec(
                region_id=rid,
                kind=kind,
                text=text,
                bbox=tuple(float(v) for v in bbox_raw),
                html=html,
                cells=region.get("cells"),
                lines=_lines_of(region.get("text") or ""),
            )
        )
    return out


# ---------------------------------------------------------------- geometry
def _bands(blocks: list[BlockSpec]) -> list[list[BlockSpec]]:
    """Nhóm block cùng hàng (overlap dọc ≥ Y_RATIO × chiều cao nhỏ hơn)."""
    order = sorted(blocks, key=lambda b: (b.y0, b.x0))
    bands: list[list[BlockSpec]] = []
    for b in order:
        for band in bands:
            ov = min(max(x.y1 for x in band), b.y1) - max(min(x.y0 for x in band), b.y0)
            if ov > 0 and ov >= Y_RATIO * min(b.h, min(x.h for x in band)):
                band.append(b)
                break
        else:
            bands.append([b])
    for band in bands:
        band.sort(key=lambda b: b.x0)
    bands.sort(key=lambda band: (band[0].y0, band[0].x0))
    return bands


def _cluster_columns(blocks: list[BlockSpec]) -> list[Col]:
    """Cùng thuật toán `render_md._cluster_columns` (sort x0, tách khi mất
    overlap) nhưng giữ toạ độ px thật của cột."""
    cols: list[Col] = []
    for b in sorted(blocks, key=lambda b: b.x0):
        if cols and b.x0 < cols[-1].x1 - X_TOL:
            cols[-1].x1 = max(cols[-1].x1, b.x1)
        else:
            cols.append(Col(b.x0, b.x1))
    return cols


def _column_defining(blocks: list[BlockSpec]) -> list[BlockSpec]:
    """Chỉ block nhiều dòng mới định nghĩa cột — hàng form (nhãn/giá trị 1
    dòng) không được biến cả trang thành 2 cột."""
    heights = [b.h for b in blocks if b.kind == "text"] or [FONT_FALLBACK]
    tall = 1.8 * statistics.median(heights)
    out = [
        b for b in blocks
        if b.kind == "text" and (len(b.lines) > 1 or b.h >= tall)
    ]
    return out


def _col_index_of(block: BlockSpec, cols: list[Col]) -> int:
    """Cột chứa tâm block; ngoài mọi cột → cột gần nhất."""
    cx = (block.x0 + block.x1) / 2
    for i, c in enumerate(cols):
        if c.x0 - X_TOL <= cx <= c.x1 + X_TOL:
            return i
    return min(
        range(len(cols)),
        key=lambda i: min(abs(cols[i].x0 - block.x0), abs(cols[i].x1 - block.x1)),
    )


def _align_of(block: BlockSpec, col: Col, tol: float) -> str:
    left_gap = max(0.0, block.x0 - col.x0)
    right_gap = max(0.0, col.x1 - block.x1)
    if left_gap > tol and abs(left_gap - right_gap) <= tol:
        return "center"
    if right_gap <= tol < left_gap:
        return "right"
    return "left"


def _first_line_indent(block: BlockSpec) -> float:
    """Không có bbox từng dòng → suy từ khoảng trắng đầu dòng (xấp xỉ, px)."""
    if len(block.lines) < 2:
        return 0.0
    indents = [len(ln) - len(ln.lstrip()) for ln in block.lines]
    delta = indents[0] - min(indents)
    return max(0.0, delta * TAB_SPACE_PX)


def _font_px(block: BlockSpec) -> float:
    return min(FONT_MAX, max(FONT_MIN, block.h))


def _attach_tabs(band: list[BlockSpec], cols: list[Col]) -> set[str]:
    """Band có ≥2 block text x-disjoint trong CÙNG cột → block trái nhất giữ
    nội dung, các block sau thành tab stop; text của chúng nối vào dòng cuối.
    Trả về id các block bị "nuốt" (không còn là block riêng)."""
    dropped: set[str] = set()
    by_col: dict[int, list[BlockSpec]] = {}
    for b in band:
        by_col.setdefault(b.col_index, []).append(b)
    for ci, group in by_col.items():
        texts = [b for b in group if b.kind == "text"]
        base = texts[0] if texts else None
        edge = base.x1 if base else 0.0
        for other in texts[1:]:
            if other.x0 - edge <= X_TOL:   # chồng x → không phải tab row
                edge = max(edge, other.x1)
                continue
            leader = "dots" if (DOTS in base.text or DOTS in other.text) else "none"
            base.tabs.append(Tab(
                pos_px=max(0.0, other.x0 - cols[ci].x0),
                align=other.align,
                leader=leader,
            ))
            value = " ".join(other.lines) or other.text.strip()
            if value:
                if base.lines:
                    base.lines[-1] += "\t" + value
                else:
                    base.lines = [value]
            dropped.add(other.region_id)
            edge = max(edge, other.x1)
    return dropped


def _page_spec(page: dict) -> PageSpec:
    width = float(page.get("width") or 1000)
    height = float(page.get("height") or 1000)
    blocks = _extract_regions(page)

    text_blocks = [b for b in blocks if b.kind == "text"]
    margin_left = (
        min(b.x0 for b in text_blocks) if text_blocks else 0.0
    )
    cols = _cluster_columns(_column_defining(blocks))
    if not cols:  # trang chỉ có hàng form / bảng → 1 cột = toàn bề ngang
        right = max((b.x1 for b in blocks), default=width)
        cols = [Col(margin_left, right)]

    tol = ALIGN_TOL_RATIO * width
    for b in blocks:
        b.col_index = _col_index_of(b, cols)
        b.font_px = _font_px(b)
        b.align = _align_of(b, cols[b.col_index], tol) if b.kind == "text" else "left"
        b.indent_px = max(0.0, b.x0 - cols[b.col_index].x0)
        b.first_line_indent_px = _first_line_indent(b)

    dropped: set[str] = set()
    for band in _bands(blocks):
        dropped |= _attach_tabs(band, cols)
    blocks = [b for b in blocks if b.region_id not in dropped]

    blocks.sort(key=lambda b: (b.col_index, b.y0, b.x0))
    for i, b in enumerate(blocks):
        same_col = [
            o for o in blocks[i + 1:] if o.col_index == b.col_index
        ]
        b.space_after_px = max(0.0, same_col[0].y0 - b.y1) if same_col else 0.0

    return PageSpec(
        width=width, height=height, margin_left=margin_left, cols=cols, blocks=blocks
    )


def build_page_specs(result: dict) -> list[PageSpec]:
    """result (spec §4) → layout spec per page."""
    return [_page_spec(pg) for pg in result.get("pages", [])]
