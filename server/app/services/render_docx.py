"""render_docx: OCR result → DOCX via LLM IR or heuristic fallback.

Flow:
  1. use_llm=True → LLM (space-bunny) → IR JSON → validate_ir() → render DOCX
  2. Fallback (LLM down / use_llm=False) → heuristic geometry-aware
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass, field

import httpx
from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, Twips
from docx.table import _Cell

from app.services.layout_spec import BlockSpec, PageSpec, build_page_specs

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.ir import (
    IRPageError, IR_PROMPT, llm_ir_pages, validate_ir, IRValidationError,
)
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger("app.services.render_docx")

# ---------------------------------------------------------------- constants
X_TOL = 4
Y_RATIO = 0.3
INDENT_UNIT = 0.06
MAX_INDENT = 6
MIN_COL_GAP = 2
TEXT_TRUNC_CHARS = 200
IMAGE_PLACEHOLDER = "[ảnh]"

_TABLE_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


# ---------------------------------------------------------------- dataclasses (heuristic fallback)
@dataclass
class Block:
    id: str
    page: int
    kind: str
    bbox: tuple
    text: str
    indent: int = 0
    align: str = "left"
    band_cols: int = 1
    # wave-3: cells-shape table (kernel parse) → docx add_table + merge span
    cells: list | None = None

    @property
    def x0(self): return self.bbox[0]
    @property
    def y0(self): return self.bbox[1]
    @property
    def x1(self): return self.bbox[2]
    @property
    def y1(self): return self.bbox[3]
    @property
    def w(self): return max(1, self.x1 - self.x0)
    @property
    def h(self): return max(1, self.y1 - self.y0)

    @property
    def lines(self) -> list[str]:
        return [ln.rstrip() for ln in self.text.splitlines() if ln.strip()]


@dataclass
class Page:
    index: int
    width: float
    height: float
    blocks: list[Block]
    margin: float = 0.0
    right: float = 0.0
    unit: float = 50.0


@dataclass
class Band:
    blocks: list[Block]
    cols: list[list[Block]] = field(default_factory=list)
    indent: int = 0

    @property
    def y0(self): return min(b.y0 for b in self.blocks)
    @property
    def y1(self): return max(b.y1 for b in self.blocks)
    @property
    def x0(self): return min(b.x0 for b in self.blocks)

    @property
    def single(self) -> Block | None:
        return self.blocks[0] if len(self.blocks) == 1 else None


# ---------------------------------------------------------------- extract (heuristic)
def extract_pages(result: dict) -> list[Page]:
    pages: list[Page] = []
    seen: set[str] = set()
    for pi, pg in enumerate(result.get("pages", [])):
        blocks: list[Block] = []
        for region in pg.get("regions", []):
            text = unicodedata.normalize("NFC", region.get("text") or "")
            is_image = bool(region.get("placeholder")) or (
                region.get("verdict") == "image_unextractable"
            )
            bbox = region.get("bbox")
            if not bbox or len(bbox) != 4:
                # P2-2: image node thiếu bbox vẫn giữ (marker render được,
                # không crash) — bbox 0-node cho geometry; text khác bị drop
                if not is_image:
                    continue
                bbox = (0, 0, 0, 0)
            # P1-R4a: image region luôn tạo node (text rỗng không bị drop ở fallback)
            if not text.strip() and not is_image:
                continue
            rid = str(region.get("id"))
            while rid in seen:
                rid = f"p{pi}-{rid}"
            seen.add(rid)
            if "<table" in text.lower() or region.get("cells"):
                kind = "table"
            elif is_image:
                kind = "image"
            else:
                kind = "text"
            blocks.append(Block(rid, pi, kind, tuple(bbox), text,
                                cells=region.get("cells")))
        w = pg.get("width") or max((b.x1 for b in blocks), default=1000)
        h = pg.get("height") or max((b.y1 for b in blocks), default=1000)
        pages.append(Page(pi, w, h, blocks))
    return pages


# ---------------------------------------------------------------- geometry (heuristic)
def _same_row(a: Block, b: Block) -> bool:
    if a.kind == "table" or b.kind == "table":
        return False
    left, right = (a, b) if a.x0 <= b.x0 else (b, a)
    if left.x1 - right.x0 > X_TOL:
        return False
    ov = min(a.y1, b.y1) - max(a.y0, b.y0)
    return ov > 0 and ov >= Y_RATIO * min(a.h, b.h)


def _build_bands(blocks: list[Block]) -> list[Band]:
    n = len(blocks)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _same_row(blocks[i], blocks[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[Block]] = {}
    for i, b in enumerate(blocks):
        groups.setdefault(find(i), []).append(b)
    bands = [Band(sorted(g, key=lambda b: (b.y0, b.x0))) for g in groups.values()]
    bands.sort(key=lambda bd: (bd.y0, bd.x0))
    return bands


def _cluster_columns(blocks: list[Block]) -> list[list[Block]]:
    cols: list[list[Block]] = []
    col_x1 = 0.0
    for b in sorted(blocks, key=lambda b: b.x0):
        if cols and b.x0 < col_x1 - X_TOL:
            cols[-1].append(b)
            col_x1 = max(col_x1, b.x1)
        else:
            cols.append([b])
            col_x1 = b.x1
    return cols


def _page_metrics(page: Page) -> None:
    texts = [b for b in page.blocks if b.kind != "table"]
    wide = [b for b in texts if b.w > 0.5 * page.width] or texts
    page.unit = max(8.0, INDENT_UNIT * page.width)
    if not wide:
        page.margin, page.right = 0.0, page.width
        return
    xs = sorted(b.x0 for b in wide)
    page.margin = statistics.median(xs[: max(1, len(xs) // 2)])
    page.right = statistics.median(b.x1 for b in wide)


def _indent_of(x0: float, page: Page) -> int:
    raw = (x0 - page.margin) / page.unit
    return min(MAX_INDENT, int(raw + 0.5)) if raw >= 0.5 else 0


def _shares_left_edge(blk: Block, page: Page) -> bool:
    tol = 0.25 * page.unit
    return sum(1 for o in page.blocks if o is not blk and abs(o.x0 - blk.x0) < tol) >= 3


def analyze(page: Page) -> list[Band]:
    _page_metrics(page)
    bands = _build_bands(page.blocks)
    cw = max(1.0, page.right - page.margin)
    page_mid = (page.margin + page.right) / 2
    for band in bands:
        band.cols = _cluster_columns(band.blocks)
        for b in band.blocks:
            b.band_cols = len(band.cols)
        blk = band.single
        if blk is None:
            band.indent = _indent_of(band.x0, page)
            continue
        raw = (blk.x0 - page.margin) / page.unit
        indent = _indent_of(blk.x0, page)
        if blk.kind != "table":
            cx = (blk.x0 + blk.x1) / 2
            if raw >= 0.6 and blk.x1 > page.right + 0.005 * page.width:
                blk.align, indent = "right", 0
            elif (raw >= 0.6 and blk.w < 0.7 * cw
                  and abs(cx - page_mid) < 0.025 * page.width
                  and not _shares_left_edge(blk, page)):
                blk.align, indent = "center", 0
            elif blk.w > 0.75 * cw:
                indent = min(indent, 1)
        blk.indent = indent
        band.indent = indent
    return bands


# ---------------------------------------------------------------- LLM
class LLMError(Exception):
    pass


async def _llm_config() -> tuple[str, str, str, float]:
    model = await get_runtime_setting(SessionLocal, "ir_llm_model", settings.ir_llm_model)
    base_url = await get_runtime_setting(SessionLocal, "llm_base_url", settings.llm_base_url)
    api_key = await get_runtime_setting(SessionLocal, "llm_api_key", settings.llm_api_key)
    timeout = await get_runtime_setting(SessionLocal, "llm_timeout", settings.llm_timeout)
    return base_url, model, api_key, timeout


async def _chat(user_content: str, json_mode: bool = True) -> str:
    base_url, model, api_key, timeout = await _llm_config()
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0,
    }
    # json_mode=False (render HTML): KHÔNG gửi response_format — json_object
    # ép model echo IR/bọc envelope thay vì HTML thô.
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            started = time.perf_counter()
            logger.info("llm called: model=%s", model)
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("llm call failed attempt=%d: %r", attempt, exc)
                if attempt:
                    raise LLMError(f"LLM không phản hồi: {exc!r}") from exc
                await asyncio.sleep(1.0)
                continue
            logger.info("llm called: model=%s status=%s elapsed=%.1fs",
                        model, resp.status_code, time.perf_counter() - started)
            if resp.status_code < 400:
                try:
                    return resp.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMError(f"phản hồi thiếu content: {exc}") from exc
            if resp.status_code in (400, 422) and json_mode:
                payload.pop("response_format", None)
            elif resp.status_code not in (429, 500, 502, 503, 504):
                raise LLMError(f"LLM HTTP {resp.status_code}")
            if attempt:
                raise LLMError(f"LLM HTTP {resp.status_code}")
            await asyncio.sleep(1.5)
    raise LLMError("LLM không phản hồi")


async def llm_ir(result: dict) -> dict:
    """Call LLM to produce IR JSON (S2: delegate shared per-page sequential,
    giữ HTTP client riêng — _chat của module, 1 shared logic trong services/ir)."""
    try:
        return await llm_ir_pages(result, _chat)
    except IRPageError as exc:
        raise LLMError(str(exc)) from exc


# ---------------------------------------------------------------- render from IR
def _borderless(table, margin_zero: bool = False) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tbl_pr.insert_element_before(
        borders, "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
        "w:tblCaption", "w:tblDescription",
    )
    if margin_zero:
        mar = OxmlElement("w:tblCellMar")
        for edge in ("top", "left", "bottom", "right"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:w"), "0")
            el.set(qn("w:type"), "dxa")
            mar.append(el)
        tbl_pr.insert_element_before(
            mar, "w:tblLook", "w:tblCaption", "w:tblDescription"
        )



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


# ---------------------------------------------------------------- render via LLM
RENDER_DOCX_PROMPT = (
    "You are a document layout renderer. Given a Document IR (nodes with bbox, "
    "type, role, align, indent) and page dimensions, render HTML for DOCX.\n"
    "Use bbox for layout: alignment, indentation, spacing.\n"
    "Map IR type → HTML: heading → h1 (document_title) / h2, paragraph → p, "
    "list → <ul><li>item</li></ul>, poem → p with lines separated by <br>, "
    "table → <table> HTML, quote → <blockquote>, caption → <p><em>text</em></p>, "
    "figure → <img src=\"crops/{rid}.png\"/> where rid = the figure node's FIRST "
    "source_block_ids entry (the builder embeds that crop; NEVER invent rid, "
    "never render figure as [ảnh] text), formula → <pre>text</pre>, separator → <hr>, "
    "footnote → <p>text</p>, form_field → <p>text</p>, page_number → skip.\n"
    "Empty zones (header/content/footer = []) → render NOTHING for that zone; "
    "do NOT invent content for missing zones. A page may have only content, "
    "only header+content, etc.\n"
    "Mỗi page IR → thẻ <page-break/> giữa các page.\n"
    "Align/indent khác mặc định → style=\"text-align:center|right|justify\" "
    "và style=\"padding-left: Nem\" (1em = 0.5 inch).\n"
    "Output raw HTML only (no code fences).\n"
    "Output raw only — do NOT wrap in JSON.\n\n"
    "Pages (index → width/height): {page_dims}\n"
    "Document IR:\n{ir_json}"
)

def _page_dims(result: dict) -> list[dict]:
    return [
        {"index": i, "width": pg.get("width"), "height": pg.get("height")}
        for i, pg in enumerate(result.get("pages", []))
    ]

async def llm_render_docx(ir_doc: DocumentIR, result: dict) -> str:
    """Render DocumentIR → HTML via LLM (dùng bbox cho layout)."""
    content = RENDER_DOCX_PROMPT.replace(
        "{page_dims}", json.dumps(_page_dims(result), ensure_ascii=False)
    ).replace("{ir_json}", ir_doc.model_dump_json())
    raw = await _chat(content, json_mode=False)
    html = raw.strip()
    m = _FENCE_RE.match(html)
    if m:
        html = m.group(1).strip()
    if not html:
        raise LLMError("LLM render trả về rỗng")
    # Model free thường bọc HTML trong JSON envelope {"output": ...} hoặc
    # echo IR JSON → unwrap field; thiếu/parsing fail → LLMError → heuristic.
    if html.startswith("{"):
        html = _unwrap_envelope(html, ("output", "html")).strip()
        if not html:
            raise LLMError("LLM render trả về rỗng")
    # HTML không tag block nào → LLMError → heuristic (chặn docx trắng 200).
    if not _BLOCK_HTML_RE.search(html) and not _TABLE_HTML_RE.search(html):
        raise LLMError("LLM render HTML không chứa tag block")
    return html


def _unwrap_envelope(text: str, keys: tuple[str, ...]) -> str:
    """JSON envelope {\"output\": ...} → field string. Fail → LLMError (heuristic)."""
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError) as exc:
        raise LLMError(f"LLM render JSON hỏng: {exc}") from exc
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
    raise LLMError(f"LLM render JSON thiếu field {'/'.join(keys)}")

_BLOCK_HTML_RE = re.compile(
    r"<(h1|h2|h3|p|blockquote|ul|li)\b([^>]*)>(.*?)</\1>", re.DOTALL | re.IGNORECASE
)
_TABLE_HTML_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_PAGE_BREAK_RE = re.compile(r"<page-break\s*/?>|<!--\s*page-break\s*-->", re.IGNORECASE)
# S1b: LLM render figure → <img src="crops/{rid}.png"> (rid = source_block_ids[0])
_IMG_SRC_RE = re.compile(
    r"<img\b[^>]*src=[\"']crops/([^\"'?#/]+)\.[a-z]+[\"'][^>]*>", re.IGNORECASE
)
_IMG_BLOCK_RE = re.compile(r"<p\b[^>]*>\s*(<img\b[^>]*>)\s*</p>", re.IGNORECASE | re.DOTALL)
# marker block: crop embed position giữ nguyên thứ tự document (regex walker)
_CIMG_RE = re.compile(r"^\[cimg:([^\]]+)\]$")
# inline tối thiểu (không HTML parser): <br> → ngắt dòng, b/i → run bold/italic
# capture group bắt buộc: split giữ lại tag → nhánh <br>/bold mới chạy
_INLINE_RE = re.compile(r"(<br\s*/?>|</?(?:strong|b|em|i)\b[^>]*>)", re.IGNORECASE)


def _add_rich_text(para, raw: str) -> None:
    """text + inline <br>/<b>/<strong>/<em>/<i> → runs (newline/bold/italic)."""
    bold = italic = False
    for part in _INLINE_RE.split(raw):
        low = part.lower()
        if low.startswith("<br"):
            para.add_run("\n")
        elif low.startswith("</"):
            if low in ("</b>", "</strong>"):
                bold = False
            elif low in ("</i>", "</em>"):
                italic = False
        elif low.startswith("<"):
            if low.startswith(("<b", "<strong")):
                bold = True
            elif low.startswith(("<i", "<em")):
                italic = True
        else:
            txt = re.sub(r"<[^>]+>", "", part)
            if txt:
                run = para.add_run(txt)
                if bold:
                    run.bold = True
                if italic:
                    run.italic = True


def _list_para(doc):
    """li → List Bullet; style thiếu → KeyError fallback indent 1 level."""
    try:
        return doc.add_paragraph(style="List Bullet")
    except KeyError:
        para = doc.add_paragraph()
        para.paragraph_format.left_indent = Inches(0.5)
        return para


async def _load_figure_crops(
    html: str, result: dict, crop_loader
) -> dict[str, bytes]:
    """S1b: rid figure phải là OCR region thật (find_region-equivalent) —
    unknown rid / loader None/fail → placeholder (partial-fail + warning)."""
    rids = {m.group(1) for m in _IMG_SRC_RE.finditer(html)}
    if not rids or crop_loader is None:
        return {}
    valid = {
        rg["id"] for pg in result.get("pages", []) for rg in pg.get("regions", [])
    }
    out: dict[str, bytes] = {}
    for rid in rids:
        if rid not in valid:
            logger.warning("docx: figure rid %s không có trong OCR — placeholder", rid)
            continue
        try:
            data = await crop_loader(rid)
        except Exception as exc:  # partial-fail: 1 crop hỏng không kill render
            logger.warning("docx: crop %s load fail — placeholder: %s", rid, exc)
            continue
        if data:
            out[rid] = data
    return out

def _html_to_docx(
    html: str,
    style_overrides: dict | None = None,
    figure_crops: dict[str, bytes] | None = None,
) -> bytes:
    """HTML (từ LLM render) → DOCX bytes.

    S1b: <img src="crops/{rid}.png"> → marker [cimg:rid] (giữ vị trí document)
    → add_picture(figure_crops[rid]); thiếu bytes → placeholder [ảnh]."""
    html = _IMG_BLOCK_RE.sub(r"\1", html)
    html = _IMG_SRC_RE.sub(lambda m: f"<p>[cimg:{m.group(1)}]</p>", html)
    doc = Document()
    chunks = _PAGE_BREAK_RE.split(html)
    for ci, chunk in enumerate(chunks):
        if ci > 0:
            doc.add_page_break()
        for m in _BLOCK_HTML_RE.finditer(chunk):
            tag = m.group(1).lower()
            attrs = m.group(2)
            inner = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if tag == "h1":
                doc.add_heading(inner, level=0)
            elif tag == "h2":
                doc.add_heading(inner, level=1)
            elif tag == "h3":
                doc.add_heading(inner, level=2)
            elif tag in ("ul", "li"):
                items = (
                    re.findall(r"<li[^>]*>(.*?)</li>", m.group(3), re.DOTALL | re.IGNORECASE)
                    if tag == "ul" else [m.group(3)]
                )
                for li in items:
                    _add_rich_text(_list_para(doc), li)
            elif (mm := _CIMG_RE.fullmatch(inner)):
                para = doc.add_paragraph()
                data = (figure_crops or {}).get(mm.group(1))
                if data:
                    try:
                        para.add_run().add_picture(io.BytesIO(data), width=Inches(6.0))
                    except Exception as exc:  # bytes hỏng → placeholder
                        logger.warning("docx: crop %s hỏng — placeholder: %s", mm.group(1), exc)
                        run = para.add_run(IMAGE_PLACEHOLDER)
                        run.italic = True
                else:
                    run = para.add_run(IMAGE_PLACEHOLDER)
                    run.italic = True
            elif inner or _INLINE_RE.search(m.group(3)):
                para = doc.add_paragraph()
                _add_rich_text(para, m.group(3))
                align = re.search(r"text-align:\s*(center|right|justify)", attrs)
                if align:
                    para.alignment = _ALIGN_MAP[align.group(1)]
                pl = re.search(r"padding-left:\s*([\d.]+)\s*em", attrs)
                if pl:
                    para.paragraph_format.left_indent = Inches(0.5 * float(pl.group(1)))
                if tag == "blockquote":
                    for run in para.runs:
                        run.italic = True
        for tbl in _TABLE_HTML_RE.findall(chunk):
            _add_html_table(doc, tbl)
    if style_overrides:
        _apply_style_overrides(doc, style_overrides)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

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



# ---------------------------------------------------------------- render from heuristic
def _render_columns(band: Band) -> list[Block]:
    """Flatten band columns into ordered block list (left-to-right, top-to-bottom)."""
    blocks: list[Block] = []
    for col in band.cols:
        blocks.extend(sorted(col, key=lambda b: b.y0))
    return blocks


def _render_band_heuristic(band: Band) -> list[Block]:
    blk = band.single
    if blk is not None and blk.kind == "table":
        return [blk]
    if blk is not None:
        return [blk]
    return _render_columns(band)


def render_page_heuristic(page: Page, bands: list[Band]) -> list[Block]:
    """Flatten bands to ordered block list for docx rendering."""
    blocks: list[Block] = []
    for band in bands:
        blocks.extend(_render_band_heuristic(band))
    return blocks


def render_from_heuristic(
    result: dict, style_overrides: dict | None = None
) -> bytes:
    """Render OCR result to DOCX using heuristic geometry."""
    pages = extract_pages(result)
    page_bands = [(pg, analyze(pg)) for pg in pages]

    doc = Document()
    for pg, bands in page_bands:
        blocks = render_page_heuristic(pg, bands)
        for b in blocks:
            if b.kind == "image":
                para = doc.add_paragraph()
                run = para.add_run(IMAGE_PLACEHOLDER)
                run.italic = True
            elif b.kind == "table":
                if b.cells:
                    _add_cells_table(doc, b.cells)  # wave-3: merge span thật
                else:
                    _add_html_table(doc, b.text)
            else:
                para = doc.add_paragraph()
                run = para.add_run(b.text)
                if b.align == "center":
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif b.align == "right":
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                if b.indent:
                    para.paragraph_format.left_indent = Inches(_INDENT_INCHES * b.indent)
        # Page break (except last page)
        if pg != pages[-1]:
            doc.add_page_break()

    if style_overrides:
        _apply_style_overrides(doc, style_overrides)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- render from layout spec
# 96 dpi giả định (PaddleOCR-VL trả px theo ảnh gốc) — px → twips/pt.
TWIPS_PER_PX = 1440 / 96
PT_PER_PX = 72 / 96
MAX_SPACE_AFTER_PT = 24.0
MAX_SECTIONS = 8            # vượt → linearize 1 cột (file docx vụn, Word khó sửa)
SEC_COL_SPACE_TWIPS = "720"

_SPEC_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
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


def _set_section_cols(section, n: int) -> None:
    """w:cols — python-docx không có API; chèn đúng vị trí schema (trước
    w:docGrid) chứ không append thô (Word có thể từ chối file)."""
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:cols")):
        sect_pr.remove(old)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), str(max(1, n)))
    cols.set(qn("w:space"), SEC_COL_SPACE_TWIPS)
    sect_pr.insert_element_before(
        cols, "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg",
        "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid",
        "w:printerSettings", "w:sectPrChange",
    )


def _add_spec_block(doc, blk: BlockSpec) -> None:
    if blk.kind == "image":
        run = doc.add_paragraph().add_run(IMAGE_PLACEHOLDER)
        run.italic = True
        return
    if blk.kind == "table":
        if blk.cells:
            _add_cells_table(doc, blk.cells)
        else:
            _add_html_table(doc, blk.html or blk.text)
        return

    para = doc.add_paragraph()
    para.alignment = _SPEC_ALIGN.get(blk.align, WD_ALIGN_PARAGRAPH.LEFT)
    pf = para.paragraph_format
    if blk.align == "left" and blk.indent_px > 0.5:
        pf.left_indent = Twips(round(blk.indent_px * TWIPS_PER_PX))
    if blk.first_line_indent_px > 0.5:
        pf.first_line_indent = Twips(round(blk.first_line_indent_px * TWIPS_PER_PX))
    for tab in blk.tabs:
        pf.tab_stops.add_tab_stop(
            Twips(round(tab.pos_px * TWIPS_PER_PX)),
            _SPEC_TAB_ALIGN.get(tab.align, WD_TAB_ALIGNMENT.LEFT),
            _SPEC_TAB_LEADER.get(tab.leader, WD_TAB_LEADER.SPACES),
        )
    pf.space_before = Pt(0)   # Word cộng space_before + space_after
    pf.space_after = Pt(
        min(MAX_SPACE_AFTER_PT, round(blk.space_after_px * PT_PER_PX, 1))
    )
    # "\n" → <w:br/>, "\t" → <w:tab/> (python-docx Run.text xử lý sẵn)
    para.add_run("\n".join(blk.lines or [blk.text]))


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


def render_docx_spec(
    result: dict, style_overrides: dict | None = None
) -> bytes:
    """OCR result → DOCX qua layout spec (không LLM, không HTML, không framePr)."""
    pages = build_page_specs(result)
    doc = Document()
    for gi, group in enumerate(_group_pages(pages)):
        if gi:
            doc.add_section(WD_SECTION_START.CONTINUOUS)
        _set_section_cols(doc.sections[-1], len(group[0].cols))
        for pg in group:
            for blk in pg.blocks:
                _add_spec_block(doc, blk)
    if style_overrides:
        _apply_style_overrides(doc, style_overrides)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

# tỉ lệ heuristic fallback / tổng lần build — quan sát model free echo/envelope
_FALLBACK_STATS = {"fallback": 0, "total": 0}


def _log_fallback(exc: Exception) -> None:
    _FALLBACK_STATS["fallback"] += 1
    logger.warning(
        "HEURISTIC FALLBACK %s — tỉ lệ %d/%d",
        type(exc).__name__, _FALLBACK_STATS["fallback"], _FALLBACK_STATS["total"],
    )

# ---------------------------------------------------------------- main API
async def build_docx(
    result: dict,
    use_llm: bool = True,
    style_overrides: dict | None = None,
    ir_sink: dict | None = None,
    crop_loader=None,
) -> bytes:
    """Build DOCX from OCR result.

    1. use_llm=True → LLM → IR → validate → render
    2. Fallback → heuristic geometry-aware

    style_overrides: jobs.layout_style applied over the finished doc
    (user's saved style wins the IR). ir_sink: optional dict filled with
    the validated IR on the LLM path (auto-gen job.ir_json — no extra call).
    crop_loader: async rid → bytes (S1b figure embed); None → placeholder.
    """
    _FALLBACK_STATS["total"] += 1
    if use_llm:
        try:
            ir_dict = await llm_ir(result)
            ir_doc = validate_ir(ir_dict, result)
            if ir_sink is not None:
                ir_sink.update(ir_dict)
            html = await llm_render_docx(ir_doc, result)
            crops = await _load_figure_crops(html, result, crop_loader)
            return _html_to_docx(html, style_overrides, figure_crops=crops)
        except (LLMError, IRValidationError) as exc:
            logger.warning("HEURISTIC FALLBACK render — layout tạm: %r", exc)
            _log_fallback(exc)

    # Heuristic fallback → layout spec tất định
    return render_docx_spec(result, style_overrides)
