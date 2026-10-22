"""layout_spec: OCR result (bbox px) → layout spec tất định.

Không LLM, không DB, không pydantic — dataclass thuần. Nguồn: spec
`docs/superpowers/specs/2026-10-20-layout-renderer-md-docx-design.md` §4.

Input: result["pages"][*] = {index, width, height,
        regions: [{id, bbox: [x0, y0, x1, y1], text, verdict, html, cells}]}
Output: list[PageSpec] — mỗi block có align/indent/tabs/spacing/font suy từ bbox.
"""

from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger("app.services.layout_spec")

# ---------------------------------------------------------------- constants
X_TOL = 4.0                 # px — 2 block coi như chồng cột
Y_RATIO = 0.5               # tỉ lệ overlap dọc tối thiểu để coi là "cùng hàng"
JUSTIFY_MIN_WIDTH_RATIO = 0.90   # block rộng ≥90% cột + ≥2 dòng → canh đều
ALIGN_TOL_RATIO = 0.02      # 2% page width — |left_gap − right_gap| < tol → center
FONT_MIN, FONT_MAX = 10.0, 48.0
FONT_FALLBACK = 16.0
DOTS = "...."               # ≥4 chấm → tab leader DOTS
TAB_SPACE_PX = 8.0          # px ước lượng cho 1 ký tự space khi tính first-line indent
FORM_RE = re.compile(r"^\S.*:\s*\.{3,}")   # "Họ và tên: ....." → form field
FORM_MAX_CHARS = 60
# cặp khối "hai bên" (header trái/phải): block phải sát mép phải + cách xa
TWO_SIDE_EDGE_RATIO = 0.05
TWO_SIDE_GAP_RATIO = 0.10         # cặp nhãn/giá trị dài hơn → coi là 2 block text thường
INDENT_SNAP_RATIO = 0.05   # thụt lề < 5% bề ngang CỘT = nhiễu → 0
COL_MIN_BLOCKS = 2          # cột phải có ≥2 block định nghĩa cột, thiếu → bỏ
HEADING_MAX_CHARS = 90     # heading thật thì ngắn; note/list dài không phải heading
HEADING_RATIO = 1.6         # font ≥ 1.6× median → heading
HEADING_L1_RATIO = 2.2      # font ≥ 2.2× median → heading level 1

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
    type_label: str = "unknown"  # paragraph|heading|form_field|table|figure|unknown
    level: int = 0               # heading level (1 = lớn nhất), 0 = không phải heading
    latex: str = ""             # LaTeX gốc nếu block là công thức ($$...$$)
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


_MATH_WRAP_RE = re.compile(r"^\s*\$\$?(.*?)\$\$?\s*$", re.S)

def _strip_math_delims(text: str) -> str:
    """Bỏ wrapper `$$ ... $$` / `$ ... $` quanh công thức.

    OCR/VLM trả LaTeX có delimiter markdown; layout chỉ render text nên giữ
    `$$` sẽ lọt vào docx ("$$ E_{n}=... $$"). Chỉ bỏ khi cả chuỗi được wrap
    (không đụng dấu $ giữa câu như giá 5$).
    """
    m = _MATH_WRAP_RE.match(text)
    return m.group(1).strip() if m else text


def _math_inner(text: str) -> str:
    """LaTeX bên trong `$$...$$` ("" nếu block không phải công thức)."""
    m = _MATH_WRAP_RE.match(text)
    return m.group(1).strip() if m else ""

_ARG = r"((?:[^{}]|\{[^{}]*\})*)"
_FRAC_RE = re.compile(r"\\frac\{" + _ARG + r"\}\{" + _ARG + r"\}")
_SUB_RE = re.compile(r"([_^])\{([^{}]*)\}")
_MATH_CMD = {
    "\\pi": "π", "\\times": "×", "\\cdot": "·", "\\le": "≤", "\\ge": "≥",
    "\\approx": "≈", "\\Delta": "Δ", "\\alpha": "α", "\\beta": "β",
    "\\mu": "µ", "\\infty": "∞", "\\pm": "±", "\\rightarrow": "→",
}

def _detex(text: str) -> str:
    """LaTeX đơn giản → text đọc được (docx/md không render math).

    ponytail: chỉ xử lý \\frac, _{} ^ {}, và vài ký hiệu phổ biến; công thức
    phức tạp vẫn còn dấu \\ — nâng lên MathML/OMML khi thật sự cần.
    """
    if "\\" not in text and not _SUB_RE.search(text):
        return text
    out = _FRAC_RE.sub(r"\1/\2", text)
    out = _SUB_RE.sub(r"\1\2", out)
    for cmd, sym in _MATH_CMD.items():
        out = out.replace(cmd, sym)
    return out.replace("{", "").replace("}", "")

def _extract_regions(page: dict) -> list[BlockSpec]:
    out: list[BlockSpec] = []
    seen: set[str] = set()
    for region in page.get("regions", []):
        raw_text = unicodedata.normalize("NFC", region.get("text") or "")
        latex = _math_inner(raw_text)
        text = _strip_math_delims(raw_text)
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
                text=_detex(text),
                bbox=tuple(float(v) for v in bbox_raw),
                html=html,
                cells=region.get("cells"),
                lines=_lines_of(_detex(text)),
                latex=latex,
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


def _drop_thin_columns(
    cols: list[Col],
    basis: list[BlockSpec],
    min_blocks: int = COL_MIN_BLOCKS,
) -> list[Col]:
    """Bỏ cột chỉ có < min_blocks block định nghĩa cột.

    Trang thật hay có header canh giữa / số trang canh phải / dòng ký tên →
    `_cluster_columns` tách thành 3-4 "cột" giả, làm docx chảy chữ vào 3-4
    cột hẹp (đo trên UNIT 1: trang 0-3 ra 3-4 cột trong khi trang chỉ 1 cột).
    Bỏ cột mảnh → block của nó về cột gần nhất qua `_col_index_of` (không mở
    rộng cột chính, nên indent/align không bị lệch).
    """
    if len(cols) <= 1 or not basis:
        return cols
    counts = [0] * len(cols)
    for b in basis:
        counts[_col_index_of(b, cols)] += 1
    kept = [c for c, n in zip(cols, counts) if n >= min_blocks]
    return kept or cols[:1]

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


def _raw_font(block: BlockSpec) -> float:
    """Font ước lượng theo TỪNG dòng, KHÔNG clamp (block.h là chiều cao cả
    khối) — cùng công thức `render_md._render` dùng, để heading không bị nhiễu
    bởi block nhiều dòng."""
    return block.h / max(1, len(block.lines))

def _font_px(block: BlockSpec) -> float:
    return min(FONT_MAX, max(FONT_MIN, _raw_font(block)))


def _covered_by_figure(block: BlockSpec, figures: list[BlockSpec]) -> bool:
    """Block nằm trong vùng x của một hình → là caption của hình, không phải
    "giá trị" của tab (bug: caption "Hình 1.1..." bị ghép vào đoạn văn bên
    trái thành 1 dòng tab)."""
    if not figures or block.kind != "text":
        return False
    bw = max(1.0, block.x1 - block.x0)
    for f in figures:
        overlap = min(block.x1, f.x1) - max(block.x0, f.x0)
        if overlap < 0.6 * bw:
            continue
        # caption nằm NGAY dưới (hoặc trong) hình — không xét block ở vùng
        # khác trang (header từng bị coi là caption của hình giữa trang).
        fh = max(1.0, f.y1 - f.y0)
        near = f.y0 - 0.3 * fh <= block.y0 <= f.y1 + 0.6 * fh
        if near:
            return True
    return False

def _attach_tabs(
    band: list[BlockSpec], cols: list[Col], figures: list[BlockSpec] | None = None
) -> set[str]:
    """Band có ≥2 block text x-disjoint trong CÙNG cột → block trái nhất giữ
    nội dung, các block sau thành tab stop; text của chúng nối vào dòng cuối.
    Cặp nhãn/giá trị cùng band, x-disjoint, text ngắn → form_field.
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
            if figures and _covered_by_figure(other, figures):
                edge = max(edge, other.x1)
                continue
            if other.x0 - edge <= X_TOL:   # chồng x → không phải tab row
                edge = max(edge, other.x1)
                continue
            leader = "dots" if (DOTS in base.text or DOTS in other.text) else "none"
            # 2 khối "hai bên" (header trái/phải, ký tên trái + ngày phải):
            # block phải kết thúc sát mép phải VÀ cách xa block trái → tab
            # RIGHT tại x1, giữ đúng vị trí như bản gốc. Cặp nhãn⇥giá trị
            # (giá trị nằm giữa dòng) vẫn tab LEFT tại x0.
            col = cols[ci]
            col_w = max(1.0, col.x1 - col.x0)
            gap = other.x0 - base.x1
            # nhãn form ("Địa chỉ: .....") không bao giờ căn phải, kể cả khi
            # giá trị dài chạm mép phải.
            is_label = bool(_LABEL_RE.search(base.text.strip()))
            # "hai bên": block trái kết thúc ở nửa trái, block phải kết thúc
            # ở 3/4 phải của cột → căn phải tại x1 (giữ vị trí như bản gốc).
            flush_right = (
                not is_label
                and base.x1 <= col.x0 + 0.5 * col_w
                and other.x1 >= col.x0 + 0.75 * col_w
            )
            base.tabs.append(Tab(
                pos_px=max(0.0, (other.x1 if flush_right else other.x0) - col.x0),
                align="right" if flush_right else other.align,
                leader=leader,
            ))
            value = " ".join(other.lines) or other.text.strip()
            if value:
                if base.lines:
                    base.lines[-1] += "\t" + value
                else:
                    base.lines = [value]
            if max(len(base.text.strip()), len(other.text.strip())) < FORM_MAX_CHARS:
                base.type_label = "form_field"
            dropped.add(other.region_id)
            edge = max(edge, other.x1)
    return dropped


_LABEL_RE = re.compile(r"[:：]\s*(\.{2,})?\s*$|\.{4,}\s*$")

def _is_form_pairs(blocks: list[BlockSpec], cols: list[Col]) -> bool:
    """Trang là FORM (nhãn ⇥ giá trị) chứ không phải 2 cột text?

    Trang form có nhiều band mà block trái nhất trông như nhãn ("Họ và tên:
     ....." / "Ngày sinh:"). Trang 2 cột text thật thì block trái là câu văn
    → không khớp. Dùng để gộp về 1 cột cho `_attach_tabs` chạy (bug: form 1
    dòng bị đọc thành 2 cột, mất tab stop).
    """
    if len(cols) < 2:
        return False
    paired = 0
    labelled = 0
    for band in _bands(blocks):
        texts = [b for b in band if b.kind == "text"]
        if len(texts) < 2:
            continue
        first = texts[0]
        if not _LABEL_RE.search(first.text.strip()):
            continue
        if any(b.col_index != first.col_index for b in texts[1:]):
            paired += 1
            labelled += 1
    return paired >= 2 and labelled == paired

def _page_spec(page: dict) -> PageSpec:
    width = float(page.get("width") or 1000)
    height = float(page.get("height") or 1000)
    blocks = _extract_regions(page)

    text_blocks = [b for b in blocks if b.kind == "text"]
    margin_left = (
        min(b.x0 for b in text_blocks) if text_blocks else 0.0
    )
    # Block nhiều dòng mới "định nghĩa" cột (hàng form 1 dòng không được biến
    # trang thành 2 cột). Trang toàn block 1 dòng (scan không tách dòng) →
    # dùng tất cả block text làm căn cứ, nếu không cột thật bị bỏ.
    col_basis = _column_defining(blocks) or [
        b for b in blocks if b.kind == "text"
    ]
    cols = _drop_thin_columns(_cluster_columns(col_basis), col_basis)
    if not cols:  # trang chỉ có bảng/form row → 1 cột = toàn bề ngang
        right = max((b.x1 for b in blocks), default=width)
        cols = [Col(margin_left, right)]
    # Form nhãn/value: 2 "cột" thực chất là 1 cột + tab stop → gộp lại.
    for b in blocks:
        b.col_index = _col_index_of(b, cols)
    if _is_form_pairs(blocks, cols):
        cols = [Col(margin_left, max((b.x1 for b in blocks), default=width))]

    figures = [b for b in blocks if b.kind == "image"]
    tol = ALIGN_TOL_RATIO * width
    for b in blocks:
        b.col_index = _col_index_of(b, cols)
        b.font_px = _font_px(b)
        b.align = _align_of(b, cols[b.col_index], tol) if b.kind == "text" else "left"
        if b.kind == "text" and _covered_by_figure(b, figures):
            b.align = "left"   # caption dưới hình: canh trái trong vùng hình
        elif (
            b.kind == "text" and b.align == "left"
            and not b.tabs and len(b.text) >= 60
        ):
            # thân bài chiếm gần hết cột → văn bản gốc canh đều 2 bên
            col = cols[b.col_index]
            col_w = max(1.0, col.x1 - col.x0)
            if (b.x1 - b.x0) >= JUSTIFY_MIN_WIDTH_RATIO * col_w:
                b.align = "justify"
        raw_indent = max(0.0, b.x0 - cols[b.col_index].x0)
        # nhiễu OCR vài px không được thành thụt lề (bản gốc không thụt)
        col_w = max(1.0, cols[b.col_index].x1 - cols[b.col_index].x0)
        b.indent_px = 0.0 if raw_indent < INDENT_SNAP_RATIO * col_w else raw_indent
        b.first_line_indent_px = _first_line_indent(b)

    dropped: set[str] = set()
    # _attach_tabs nhóm theo col_index nên chỉ ghép tab TRONG cùng cột — an
    # toàn cho trang nhiều cột (bug trước đây là do cột bị nhận sai thành 1).
    for band in _bands(blocks):
        dropped |= _attach_tabs(band, cols, figures)
    blocks = [b for b in blocks if b.region_id not in dropped]

    blocks.sort(key=lambda b: (b.col_index, b.y0, b.x0))
    for i, b in enumerate(blocks):
        same_col = [
            o for o in blocks[i + 1:] if o.col_index == b.col_index
        ]
        b.space_after_px = max(0.0, same_col[0].y0 - b.y1) if same_col else 0.0

    _label_types(blocks)
    return PageSpec(
        width=width, height=height, margin_left=margin_left, cols=cols, blocks=blocks
    )

def _label_types(blocks: list[BlockSpec]) -> None:
    """type_label + heading level: tất định, chỉ từ font & text (không LLM).
    Giữ `kind` cũ cho renderer."""
    fonts = [_raw_font(b) for b in blocks if b.kind == "text"]
    median = statistics.median(fonts) if fonts else 0.0
    for b in blocks:
        if b.type_label == "form_field":
            continue
        font = _raw_font(b)
        if b.kind == "table":
            b.type_label = "table"
        elif b.kind == "image":
            b.type_label = "figure"
        elif FORM_RE.match(b.text.strip()):
            b.type_label = "form_field"
        elif median and font >= HEADING_L1_RATIO * median:
            if len(b.text) <= HEADING_MAX_CHARS and len(b.lines) <= 2:
                b.type_label, b.level = "heading", 1
            else:
                b.type_label = "paragraph"
        elif median and font >= HEADING_RATIO * median:
            if len(b.text) <= HEADING_MAX_CHARS and len(b.lines) <= 2:
                b.type_label, b.level = "heading", 2
            else:
                b.type_label = "paragraph"
        else:
            b.type_label = "paragraph"


def build_page_specs(result: dict) -> list[PageSpec]:
    """result (spec §4) → layout spec per page."""
    return [_page_spec(pg) for pg in result.get("pages", [])]
