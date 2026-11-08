"""render_docx: OCR result → DOCX via layout_spec (0 LLM calls).

Flow: render_docx_spec() — section/column/indent/tab từ layout spec; không
LLM, không HTML render, không framePr.
"""

from __future__ import annotations

import io
import statistics
from dataclasses import dataclass
import logging
import re

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER,
)
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, Twips
from docx.table import _Cell

from app.services.ir import spec_ir
from app.services.layout_spec import (
    FONT_FALLBACK,
    BlockSpec,
    Col,
    PageSpec,
    Tab,
)

logger = logging.getLogger("app.services.render_docx")

# ---------------------------------------------------------------- constants
IMAGE_PLACEHOLDER = "[ảnh]"


# ---------------------------------------------------------------- render from IR
def _html_table_rows(text: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL | re.IGNORECASE):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.DOTALL | re.IGNORECASE
            )
        ]
        if cells:
            rows.append(cells)
    return rows


def _add_html_table(container, text: str) -> bool:
    rows = _html_table_rows(text)
    if not rows:
        return False
    if isinstance(container, _Cell):
        p0 = container.paragraphs[0]
        if not p0.text and len(container.paragraphs) == 1:
            p0._element.getparent().remove(p0._element)
    cols = max(len(r) for r in rows)
    table = container.add_table(rows=len(rows), cols=cols)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            table.rows[ri].cells[ci].paragraphs[0].add_run(val)
    return True

def _add_cells_table(container, cells: list[list[dict]]) -> bool:
    """wave-3: cells (kernel parse, có rowspan/colspan/header) → docx table
    python-docx với merge() thật (gridSpan/vMerge) — fidelity 100%, html
    regex path không có span.

    Ceiling: grid ncols = hàng sum colspan lớn nhất (rowspan-tiếp-chéo không
    nới rộng grid) — đủ cho bảng VLM; upgrade path = occupancy scan đầy đủ."""
    rows = len(cells)
    ncols = max(
        (sum(max(1, int(c.get("colspan") or 1)) for c in row) for row in cells),
        default=0,
    )
    if not rows or not ncols:
        return False
    if isinstance(container, _Cell):
        p0 = container.paragraphs[0]
        if not p0.text and len(container.paragraphs) == 1:
            p0._element.getparent().remove(p0._element)
    table = container.add_table(rows=rows, cols=ncols)
    grid: list[list[tuple[int, int] | None]] = [[None] * ncols for _ in range(rows)]
    for ri, row in enumerate(cells):
        ci = 0
        for cell in row:
            while ci < ncols and grid[ri][ci] is not None:
                ci += 1
            if ci >= ncols:
                break
            rs = max(1, int(cell.get("rowspan") or 1))
            cs = max(1, int(cell.get("colspan") or 1))
            for dr in range(rs):
                for dc in range(cs):
                    if ri + dr < rows and ci + dc < ncols:
                        grid[ri + dr][ci + dc] = (ri, ci)
            anchor = table.cell(ri, ci)
            anchor.paragraphs[0].add_run(str(cell.get("text") or ""))
            if rs > 1 or cs > 1:
                end = table.cell(min(ri + rs - 1, rows - 1),
                                 min(ci + cs - 1, ncols - 1))
                anchor.merge(end)
            ci += cs
    return True


_ALIGN_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_INDENT_INCHES = 0.5


def _all_paragraphs(container):
    """Body + table-cell paragraphs (merged cells repeat in row.cells — idempotent)."""
    for para in container.paragraphs:
        yield para
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _all_paragraphs(cell)

def _apply_style_overrides(doc, ov: dict) -> None:
    """User style (jobs.layout_style) → every paragraph/run (user beats IR)."""
    font = ov.get("fontFamily")
    size = ov.get("fontSize")
    align = _ALIGN_MAP.get(ov.get("align"))
    indent = ov.get("indent")
    spacing = ov.get("spacing")
    underline = ov.get("underline")
    for para in _all_paragraphs(doc):
        if align is not None:
            para.alignment = align
        if indent is not None:  # 0 → left_indent 0 (explicit clear)
            para.paragraph_format.left_indent = Inches(_INDENT_INCHES * indent)
        if spacing is not None:
            para.paragraph_format.line_spacing = float(spacing)
        for run in para.runs:
            if font is not None:
                run.font.name = font
            if size is not None:
                run.font.size = Pt(size)
            if underline is not None:
                run.underline = underline



# ---------------------------------------------------------------- render from layout spec
# 96 dpi giả định (PaddleOCR-VL trả px theo ảnh gốc) — px → twips/pt.
TWIPS_PER_PX = 1440 / 96
# Bề ngang vùng chữ của trang Letter mặc định (12240 − 1800×2 twips). Toạ độ
# của spec là px trên ảnh scan (640…1500 px) → phải scale về twips theo đúng
# tỉ lệ này, nếu không indent/tab/cột rộng gấp ~1.8 lần và Word bóp méo.
TEXT_WIDTH_TWIPS = 8640.0
PT_PER_PX = 72 / 96
MAX_SPACE_AFTER_PT = 24.0
MAX_SECTIONS = 8            # vượt → linearize 1 cột (file docx vụn, Word khó sửa)
SEC_COL_SPACE_TWIPS = "720"

_SPEC_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_SPEC_TAB_ALIGN = {
    "left": WD_TAB_ALIGNMENT.LEFT,
    "center": WD_TAB_ALIGNMENT.CENTER,
    "right": WD_TAB_ALIGNMENT.RIGHT,
}
_SPEC_TAB_LEADER = {
    "none": WD_TAB_LEADER.SPACES,   # val="none" (default OOXML)
    "dots": WD_TAB_LEADER.DOTS,
}


def _scale_for(page_width: float) -> float:
    """px (bề ngang trang scan) → twips (vùng chữ docx)."""
    return TEXT_WIDTH_TWIPS / max(1.0, page_width * TWIPS_PER_PX)


A4_W = 11906.0
A4_H = 16838.0
MARGIN_MIN_TW = 567.0   # 1cm — Word/LibreOffice coi margin ~0 là lỗi in

@dataclass
class PageGeometry:
    """Khung trang Word suy từ chính trang gốc: khổ A4 + lề = vùng trắng của bản
    scan, để bề ngang vùng chữ ≈ bản gốc (trước đây ép mọi trang về 6in → chữ
    phải thu nhỏ ~35% mới vừa, tràn trang)."""
    scale: float        # px → twips của khung A4
    text_width: float   # twips
    margins: tuple[float, float, float, float]  # left, right, top, bottom

def _page_geometry(page: dict) -> PageGeometry:
    width = float(page.get("width") or 0.0) or 1.0
    height = float(page.get("height") or 0.0) or 1.0
    scale = A4_W / (width * TWIPS_PER_PX)
    boxes = [
        (n.get("render") or {}).get("bbox_exact")
        for n in page.get("content") or []
    ]
    boxes = [b for b in boxes if b and len(b) == 4]
    if boxes:
        left = min(b[0] for b in boxes)
        right = width - max(b[2] for b in boxes)
        top = min(b[1] for b in boxes)
        bottom = height - max(b[3] for b in boxes)
    else:
        left = right = top = bottom = 0.0
    px = TWIPS_PER_PX * scale
    margins = tuple(
        max(MARGIN_MIN_TW if i < 2 else 0.0, round(v * px))
        for i, v in enumerate((left, right, top, bottom))
    )
    text_width = A4_W - margins[0] - margins[1]
    return PageGeometry(scale=scale, text_width=text_width, margins=margins)

def _page_metrics(page: dict, geo: PageGeometry) -> tuple[float, float] | None:
    """IR page → (font_pt, line_pitch_pt) theo đúng khung trang của trang gốc.

    Nhịp dòng = median khoảng cách đỉnh-dòng liên tiếp; cỡ chữ suy từ nhịp dòng
    (chữ thật ≈ pitch/1,25 với giãn dòng đơn), KHÔNG từ chiều cao bbox (bbox
    phình vì dấu + khoảng trắng → chữ to hơn bản gốc).
    """
    tops: list[float] = []
    for node in page.get("content") or []:
        bbox = (node.get("render") or {}).get("bbox_exact")
        if bbox and len(bbox) == 4:
            tops.append(float(bbox[1]))
    uniq = sorted(set(round(t, 1) for t in tops))
    gaps = [b - a for a, b in zip(uniq, uniq[1:]) if b - a >= 4]
    if not gaps:
        return None
    pitch_pt = statistics.median(gaps) * PT_PER_PX * geo.scale
    return pitch_pt / 1.25, pitch_pt

def _apply_page_metrics(doc, pages: list[dict], geo: PageGeometry) -> None:
    """Cỡ chữ + giãn dòng khớp bản gốc (1 lần cho cả document).

    Heading co theo cùng tỉ lệ để không phá hệ cấp bậc; space_after từng block
    vẫn do block quyết (đã nhân scale ở `_add_spec_block`).
    """
    if not pages:
        return
    metrics = _page_metrics(pages[0], geo)
    if metrics is None:
        return
    font_pt, pitch_pt = metrics
    font_pt = max(6.0, min(12.0, round(font_pt, 1)))
    pitch_pt = max(font_pt * 1.05, round(pitch_pt, 1))
    normal = doc.styles["Normal"]
    normal.font.size = Pt(font_pt)
    normal.paragraph_format.line_spacing = Pt(pitch_pt)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    ratio = font_pt / 11.0
    for name, base in (("Heading 1", 16.0), ("Heading 2", 13.0), ("Heading 3", 12.0)):
        if name in [st.name for st in doc.styles]:
            doc.styles[name].font.size = Pt(round(base * ratio, 1))

def _apply_page_setup(section, geo: PageGeometry) -> None:
    section.page_width = Twips(A4_W)
    section.page_height = Twips(A4_H)
    left, right, top, bottom = geo.margins
    section.left_margin = Twips(left)
    section.right_margin = Twips(right)
    section.top_margin = Twips(top)
    section.bottom_margin = Twips(bottom)

def _set_section_cols(
    section,
    cols: list,
    n: int | None = None,
    scale: float = 1.0,
    text_width: float = TEXT_WIDTH_TWIPS,
) -> None:
    """w:cols — python-docx không có API; chèn đúng vị trí schema.

    Cột không đều bề ngang phải khai báo từng `w:col w:w` + equalWidth=0, nếu
    chỉ `w:num` Word chia đều → lệch bản gốc. Bề ngang + rãnh được CHUẨN HOÁ
    cho vừa vùng chữ của Word (trước đây dùng px tuyệt đối → 4 cột chỉ chiếm
    52% bề ngang, LibreOffice vẽ chồng chữ lên nhau).
    """
    sect_pr = section._sectPr
    for old_el in sect_pr.findall(qn("w:cols")):
        sect_pr.remove(old_el)
    cols_el = OxmlElement("w:cols")
    count = max(1, n if n is not None else len(cols))
    cols_el.set(qn("w:num"), str(count))
    if count > 1 and len(cols) == count:
        span_px = max(1.0, cols[-1].x1 - cols[0].x0)
        gaps_px = [max(0.0, cols[i + 1].x0 - cols[i].x1) for i in range(count - 1)]
        norm = text_width / span_px
        widths = [max(1, round((c.x1 - c.x0) * norm)) for c in cols]
        gaps = [max(0, round(g * norm)) for g in gaps_px]
        cols_el.set(qn("w:equalWidth"), "0")
        for i, width in enumerate(widths):
            col_el = OxmlElement("w:col")
            col_el.set(qn("w:w"), str(width))
            if i < count - 1:      # w:space = khoảng cách SAU cột này
                col_el.set(qn("w:space"), str(gaps[i] or SEC_COL_SPACE_TWIPS))
            cols_el.append(col_el)
    else:
        cols_el.set(qn("w:space"), SEC_COL_SPACE_TWIPS)
    sect_pr.insert_element_before(
        cols_el, "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg",
        "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid",
        "w:printerSettings", "w:sectPrChange",
    )

def _add_image_block(
    doc, blk: BlockSpec, crops: dict[str, bytes], scale: float = 1.0
) -> None:
    """Crop bytes cho region_id → ảnh đúng bbox width; thiếu/lỗi → placeholder."""
    data = crops.get(blk.region_id)
    if data:
        try:
            para = doc.add_paragraph()
            para.alignment = _SPEC_ALIGN.get(blk.align, WD_ALIGN_PARAGRAPH.LEFT)
            para.add_run().add_picture(
                io.BytesIO(data), width=Twips(round(blk.w * TWIPS_PER_PX * scale))
            )
            return
        except Exception as exc:  # ảnh hỏng → giữ placeholder, không crash
            logger.info("crop rid=%s lỗi: %r — placeholder", blk.region_id, exc)
    run = doc.add_paragraph().add_run(IMAGE_PLACEHOLDER)
    run.italic = True

def _omml_of(latex: str) -> str | None:
    """LaTeX → OMML (Office Math). None nếu thiếu lib hoặc latex lỗi.

    ponytail: chỉ block công thức ($$...$$) đi đường này; công thức inline
    trong câu vẫn là text. Thêm inline khi thật sự cần.
    """
    try:
        from latex2mathml.converter import convert as _l2m
        from mathml2omml import convert as _m2o
    except ImportError:      # pragma: no cover - dep là main dep
        return None
    try:
        omml = _m2o(_l2m(latex))
    except Exception as exc:  # latex lạ/không parse được → dùng text detex
        logger.info("latex→OMML failed (%r): %r", latex[:40], exc)
        return None
    if not omml or "<m:oMath" not in omml:
        return None
    return omml


def _add_math_block(doc, blk: BlockSpec, omml: str) -> None:
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = para.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(min(MAX_SPACE_AFTER_PT, round(blk.space_after_px * PT_PER_PX, 1)))
    xml = omml if "xmlns:m=" in omml else omml.replace(
        "<m:oMath", f"<m:oMath {nsdecls('m', 'w')}", 1
    )
    para._p.append(parse_xml(xml))


def _add_spec_block(
    doc, blk: BlockSpec, crops: dict[str, bytes] | None = None,
    scale: float = 1.0,
) -> None:
    if blk.kind == "image":
        _add_image_block(doc, blk, crops or {}, scale)
        return
    if blk.kind == "table":
        if blk.cells:
            _add_cells_table(doc, blk.cells)
        else:
            _add_html_table(doc, blk.html or blk.text)
        return

    if blk.latex:
        omml = _omml_of(blk.latex)
        if omml:
            _add_math_block(doc, blk, omml)
            return
    para = doc.add_paragraph()
    # 2026-11-07: level do IR quyết (cùng nguồn với dấu # của md) → Word có
    # Heading style thật thay vì paragraph thường.
    if blk.kind == "text" and blk.level > 0:
        style_name = f"Heading {min(blk.level, 3)}"
        if style_name in [s.name for s in doc.styles]:
            para.style = doc.styles[style_name]
    para.alignment = _SPEC_ALIGN.get(blk.align, WD_ALIGN_PARAGRAPH.LEFT)
    pf = para.paragraph_format
    if blk.align == "left" and blk.indent_px > 0.5:
        pf.left_indent = Twips(round(blk.indent_px * TWIPS_PER_PX * scale))
    if blk.first_line_indent_px > 0.5:
        pf.first_line_indent = Twips(
            round(blk.first_line_indent_px * TWIPS_PER_PX * scale)
        )
    for tab in blk.tabs:
        pf.tab_stops.add_tab_stop(
            Twips(round(tab.pos_px * TWIPS_PER_PX * scale)),
            _SPEC_TAB_ALIGN.get(tab.align, WD_TAB_ALIGNMENT.LEFT),
            _SPEC_TAB_LEADER.get(tab.leader, WD_TAB_LEADER.SPACES),
        )
    pf.space_before = Pt(0)   # Word cộng space_before + space_after
    pf.space_after = Pt(
        min(MAX_SPACE_AFTER_PT, round(blk.space_after_px * PT_PER_PX * scale, 1))
    )
    # "\n" → <w:br/>, "\t" → <w:tab/> (python-docx Run.text xử lý sẵn)
    # KHÔNG ép cỡ chữ/giãn dòng theo bbox ở đây: đo bằng vòng VLM preview
    # (job 84) thấy chữ tràn sang cột bên cạnh và các cột lệch đỉnh, tệ hơn
    # để Word dùng mặc định. Cần cỡ chữ thì làm theo cặp (font_px, median)
    # của trang, kèm test render thật.
    para.add_run("\n".join(blk.lines or [blk.text]))


def _block_of(node: dict):
    """Node IR → BlockSpec (view) để walker docx dùng lại nguyên vẹn.

    IR mang đủ dữ liệu (render.style + bbox_exact + lines/cells/latex) nên
    KHÔNG đọc lại layout_spec; node IR cũ (không có `render`) → None (bỏ qua).
    """
    render = node.get("render")
    if not render:
        return None
    style = render.get("style") or {}
    bbox = render.get("bbox_exact") or node.get("bbox") or [0, 0, 1, 1]
    x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    rid = render.get("image_region_id") or next(
        iter(node.get("source_block_ids") or []), ""
    )
    return BlockSpec(
        region_id=rid,
        kind=render.get("kind") or "text",
        text=node.get("text") or "",
        bbox=(x0, y0, x1, y1),
        col_index=int(style.get("col_index") or 0),
        align=style.get("align") or "left",
        indent_px=float(style.get("indent_px") or 0.0),
        first_line_indent_px=float(style.get("first_line_indent_px") or 0.0),
        tabs=[
            Tab(float(t.get("pos_px") or 0.0), t.get("align") or "left", t.get("leader") or "none")
            for t in (style.get("tabs") or [])
        ],
        space_after_px=float(style.get("space_after_px") or 0.0),
        font_px=float(style.get("font_px") or 0.0) or FONT_FALLBACK,
        type_label=node.get("type") or "paragraph",
        level=int(style.get("level") or 0),
        latex=render.get("latex") or "",
        html=render.get("html") or "",
        cells=render.get("cells"),
        lines=list(render.get("lines") or []),
    )


def _group_pages(pages: list[PageSpec]) -> list[list[PageSpec]]:
    """Trang liên tiếp cùng số cột → 1 section (linearize nếu quá nhiều)."""
    groups: list[list[PageSpec]] = []
    for pg in pages:
        if groups and len(groups[-1][0].cols) == len(pg.cols):
            groups[-1].append(pg)
        else:
            groups.append([pg])
    if len(groups) > MAX_SECTIONS:
        logger.warning(
            "docx spec: %d section > %d — linearize 1 cột", len(groups), MAX_SECTIONS
        )
        return [pages] if pages else []
    return groups


def _page_bands(page: dict) -> list[tuple[list[Col], float, list[BlockSpec]]]:
    """IR page → [(cols, page_width, blocks)] theo từng DẢI NGANG.

    Trang trộn bố cục (đề bài 1 cột trên, thân báo 4 cột giữa, dòng kết 1 cột)
    → mỗi dải là 1 section của Word; IR cũ (không có bands) → cả trang 1 dải.
    """
    width = float(page.get("width") or 0.0)
    by_id = {
        n["id"]: b
        for n in page.get("content") or []
        for b in [_block_of(n)]
        if b is not None
    }
    bands = page.get("bands") or []
    out: list[tuple[list[Col], float, list[BlockSpec]]] = []
    if bands:
        seen: set[str] = set()
        for band in bands:
            cols = [Col(float(c[0]), float(c[1])) for c in band.get("columns") or []]
            blocks: list[BlockSpec] = []
            for nid in band.get("node_ids") or []:
                blk = by_id.get(nid)
                if blk is not None and nid not in seen:
                    seen.add(nid)
                    blocks.append(blk)
            if blocks:
                out.append((cols or [Col(0.0, width or 1.0)], width, blocks))
        rest = [b for nid, b in by_id.items() if nid not in seen]
        if rest:
            out.append(([Col(0.0, width or 1.0)], width, rest))
    else:
        cols = [Col(float(c[0]), float(c[1])) for c in page.get("columns") or []]
        out.append(
            (cols or [Col(0.0, width or 1.0)], width, list(by_id.values()))
        )
    return out


def render_docx_ir(
    ir: dict,
    style_overrides: dict | None = None,
    crops: dict[str, bytes] | None = None,
) -> bytes:
    """Document IR → DOCX (0 LLM, không HTML, không framePr).

    Mỗi DẢI NGANG của trang = 1 section (grid cột riêng). Trang OCR mới → page
    break, giữ ranh giới trang gốc. crops: {region_id: bytes} — thiếu → placeholder.
    """
    doc = Document()
    pages = ir.get("pages") or []
    page_scale = 1.0
    if pages:
        geo = _page_geometry(pages[0])
        page_scale = geo.scale
        _apply_page_metrics(doc, pages, geo)
    first = True
    for page in pages:
        for bi, (cols, width, blocks) in enumerate(_page_bands(page)):
            if first:
                first = False
            else:
                doc.add_section(WD_SECTION_START.CONTINUOUS)
            if pages:
                _apply_page_setup(doc.sections[-1], geo)
                _set_section_cols(
                    doc.sections[-1], cols, scale=page_scale, text_width=geo.text_width
                )
            else:  # pragma: no cover - IR rỗng
                _set_section_cols(doc.sections[-1], cols, scale=_scale_for(width))
            for blk in blocks:
                _add_spec_block(doc, blk, crops, page_scale)
        if not first:
            doc.add_page_break()
    if style_overrides:
        _apply_style_overrides(doc, style_overrides)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_docx_spec(
    result: dict,
    style_overrides: dict | None = None,
    crops: dict[str, bytes] | None = None,
) -> bytes:
    """OCR result → DOCX: dựng IR rồi render từ IR (một đường duy nhất)."""
    return render_docx_ir(spec_ir(result), style_overrides, crops)


async def _load_crops(result: dict, crop_loader) -> dict[str, bytes] | None:
    """Gom crop bytes cho mọi block image (gọi loader TUẦN TỰ, lỗi/None → bỏ)."""
    if crop_loader is None:
        return None
    crops: dict[str, bytes] = {}
    for page in spec_ir(result).get("pages") or []:
        for node in page.get("content") or []:
            blk = _block_of(node)
            if blk is None or blk.kind != "image" or blk.region_id in crops:
                continue
            try:
                data = await crop_loader(blk.region_id)
            except Exception as exc:  # partial-fail: crop thiếu → placeholder
                logger.info("crop loader rid=%s failed: %r", blk.region_id, exc)
                continue
            if data:
                crops[blk.region_id] = data
    return crops

async def build_docx(
    result: dict,
    use_llm: bool = True,
    style_overrides: dict | None = None,
    ir_sink: dict | None = None,
    crop_loader=None,
) -> bytes:
    """Build DOCX from OCR result — layout_spec only (0 LLM call).

    crop_loader: async (rid) → bytes | None — wire crop on-demand (batch
    artifact → get_or_make_crop + storage.get); None/lỗi → placeholder.
    ponytail: use_llm/ir_sink giữ cho tương thích test; xoá khi test cập nhật.
    style_overrides (jobs.layout_style) áp sau cùng.
    """
    crops = await _load_crops(result, crop_loader)
    return render_docx_spec(result, style_overrides, crops)
