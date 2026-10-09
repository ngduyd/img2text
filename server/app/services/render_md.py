"""render_md: OCR result → Markdown via LLM IR or heuristic fallback.

Flow:
  1. use_llm=True → LLM (space-bunny) → IR JSON → validate_ir() → render MD
  2. Fallback (LLM down / use_llm=False) → heuristic geometry-aware

Heuristic fallback copied from llm_md.py: _build_bands, _cluster_columns,
_render_band, _indent_of, _same_cluster.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.ir import DocumentIR, IR_PROMPT, validate_ir, IRValidationError
from app.services.runtime_settings import get_runtime_setting

logger = logging.getLogger("render_md")

# ---------------------------------------------------------------- constants
X_TOL = 4
Y_RATIO = 0.3
INDENT_UNIT = 0.06
MAX_INDENT = 6
MIN_COL_GAP = 2
LLM_CHUNK = 120
TEXT_PREVIEW = 160

_TABLE_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_HEAD_RE = re.compile(r"^(câu|bài|phần|chương|mục|question|part|section)\s*[\dIVXivx]+", re.I)
_ROMAN_RE = re.compile(r"^[IVX]+[.)]\s")


# ---------------------------------------------------------------- dataclasses
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
    label: dict = field(default_factory=dict)

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


# ---------------------------------------------------------------- extract
def extract_pages(result: dict) -> list[Page]:
    pages: list[Page] = []
    seen: set[str] = set()
    for pi, pg in enumerate(result.get("pages", [])):
        blocks: list[Block] = []
        for region in pg.get("regions", []):
            text = unicodedata.normalize("NFC", region.get("text") or "")
            bbox = region.get("bbox")
            if not text.strip() or not bbox or len(bbox) != 4:
                continue
            rid = str(region.get("id"))
            while rid in seen:
                rid = f"p{pi}-{rid}"
            seen.add(rid)
            if "<table" in text.lower():
                kind = "table"
            elif region.get("placeholder") or region.get("verdict") == "image_unextractable":
                kind = "image"
            else:
                kind = "text"
            blocks.append(Block(rid, pi, kind, tuple(bbox), text))
        w = pg.get("width") or max((b.x1 for b in blocks), default=1000)
        h = pg.get("height") or max((b.y1 for b in blocks), default=1000)
        pages.append(Page(pi, w, h, blocks))
    return pages


# ---------------------------------------------------------------- geometry
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


def _same_cluster(a: Band, b: Band) -> bool:
    x, y = a.single, b.single
    if x is None or y is None:
        return False
    y_gap = y.y0 - x.y1
    if y_gap > 20:
        return False
    text_x = (x.lines[0] if x.lines else "")
    text_y = (y.lines[0] if y.lines else "")
    cx = re.match(r"^Câu\s+(\d+)", text_x, re.I)
    cy = re.match(r"^Câu\s+(\d+)", text_y, re.I)
    if cx and cy and cx.group(1) != cy.group(1):
        return False
    return True


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
    cluster: list[Band] = []
    prev: Band | None = None
    for band in bands:
        blk = band.single
        if blk is None:
            continue
        if prev is not None and _same_cluster(prev, band):
            cluster.append(band)
        else:
            if cluster:
                ci = max(b.indent for b in cluster)
                for b in cluster:
                    b.indent = ci
            cluster = [band]
        prev = band
    if cluster:
        ci = max(b.indent for b in cluster)
        for b in cluster:
            b.indent = ci
    return bands


# ---------------------------------------------------------------- heuristic labels
def heuristic_labels(pages: list[Page]) -> dict[str, dict]:
    labels: dict[str, dict] = {}
    for pg in pages:
        for b in pg.blocks:
            if b.kind != "text" or b.band_cols > 1:
                continue
            first = (b.lines or [""])[0].strip()
            if _HEAD_RE.match(first) or _ROMAN_RE.match(first):
                labels[b.id] = {"h": 2}
    return labels


# ---------------------------------------------------------------- LLM
class LLMError(Exception):
    pass


async def _llm_config() -> tuple[str, str, str, float]:
    model = await get_runtime_setting(SessionLocal, "ir_llm_model", settings.ir_llm_model)
    base_url = await get_runtime_setting(SessionLocal, "llm_base_url", settings.llm_base_url)
    api_key = await get_runtime_setting(SessionLocal, "llm_api_key", settings.llm_api_key)
    return base_url, model, api_key, settings.llm_timeout


async def _chat(user_content: str) -> str:
    base_url, model, api_key, timeout = await _llm_config()
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            started = time.perf_counter()
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("llm call failed: %s", exc)
                if attempt:
                    raise LLMError(f"LLM không phản hồi: {exc}") from exc
                await asyncio.sleep(1.0)
                continue
            logger.info("llm called: model=%s status=%s elapsed=%.1fs",
                        model, resp.status_code, time.perf_counter() - started)
            if resp.status_code < 400:
                try:
                    return resp.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMError(f"phản hồi thiếu content: {exc}") from exc
            if resp.status_code in (400, 422):
                payload.pop("response_format", None)
            elif resp.status_code not in (429, 500, 502, 503, 504):
                raise LLMError(f"LLM HTTP {resp.status_code}")
            if attempt:
                raise LLMError(f"LLM HTTP {resp.status_code}")
            await asyncio.sleep(1.5)
    raise LLMError("LLM không phản hồi")


async def llm_ir(result: dict) -> dict:
    """Call LLM to produce IR JSON from OCR result."""
    ocr_json = json.dumps(result, ensure_ascii=False)
    # replace (not format): prompt contains literal {schema} braces
    content = IR_PROMPT.replace("{ocr_json}", ocr_json)
    raw = await _chat(content)
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    start = text.find("{")
    if start == -1:
        raise LLMError("IR không chứa JSON object")
    try:
        # raw_decode: lấy object JSON đầu tiên, bỏ phần thừa LLM nối sau
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except (ValueError, TypeError) as exc:
        raise LLMError(f"IR không phải JSON: {exc}") from exc


# ---------------------------------------------------------------- render from IR
def _table_md(html_text: str) -> list[str]:
    rows: list[list[str]] = []
    for row in _TABLE_ROW_RE.findall(html_text):
        cells = []
        for c in _TABLE_CELL_RE.findall(row):
            c = html.unescape(_TAG_RE.sub(" ", c))
            c = re.sub(r"\s+", " ", c).strip().replace("|", "\\|")
            cells.append(c)
        if cells:
            rows.append(cells)
    if not rows:
        return [re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", html_text))).strip()]
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * n) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out


RENDER_MD_PROMPT = (
    "You are a document layout renderer. Given a Document IR (nodes with bbox, "
    "type, role, align, indent) and page dimensions, render Markdown.\n"
    "Use bbox for layout: alignment, indentation, spacing.\n"
    "Map IR type → markdown: heading → # (document_title → #, else ##), "
    "paragraph → text, list → - item, poem → indented lines (4 spaces), "
    "table → markdown table (parse <table> HTML), quote → >, caption → *italic*, "
    "figure → [figure: text], formula → ```\\n...\\n```, separator → ---, "
    "footnote → [text], form_field → [form: text], page_number → skip.\n"
    "Output raw markdown only (no code fences).\n\n"
    "Pages (index → width/height): {page_dims}\n"
    "Document IR:\n{ir_json}"
)

def _page_dims(result: dict) -> list[dict]:
    return [
        {"index": i, "width": pg.get("width"), "height": pg.get("height")}
        for i, pg in enumerate(result.get("pages", []))
    ]

async def llm_render_md(ir_doc: DocumentIR, result: dict) -> str:
    """Render DocumentIR → markdown via LLM (dùng bbox cho layout)."""
    content = RENDER_MD_PROMPT.replace(
        "{page_dims}", json.dumps(_page_dims(result), ensure_ascii=False)
    ).replace("{ir_json}", ir_doc.model_dump_json())
    raw = await _chat(content)
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    if not text:
        raise LLMError("LLM render trả về rỗng")
    # LLM thỉnh thoảng echo lại IR JSON thay vì render → coi là fail, rơi
    # về heuristic (render thủ công). Markdown không bao giờ bắt đầu bằng {.
    if text.startswith("{") and ('"document_id"' in text or '"pages"' in text):
        raise LLMError("LLM render trả về IR JSON, không phải markdown")
    return text




# ---------------------------------------------------------------- render from heuristic
def _fmt_lines(b: Block) -> list[str]:
    lab = b.label
    h = lab.get("h", 0)
    out = []
    for i, ln in enumerate(b.lines):
        if lab.get("bold") and not h:
            ln = f"**{ln}**"
        if i == 0 and h:
            ln = f"{'#' * h} {ln}"
        if lab.get("quote"):
            ln = f"> {ln}"
        out.append(ln)
    return out


def _render_columns(band: Band) -> list[str]:
    blocks = band.blocks
    cpx_samples = [b.w / max(len(l) for l in b.lines) for b in blocks if b.lines]
    cpx = max(1.0, statistics.median(cpx_samples)) if cpx_samples else 8.0
    lh = max(1.0, statistics.median(b.h / max(1, len(b.lines)) for b in blocks))
    base = band.y0

    cells: list[dict[int, str]] = []
    for col in band.cols:
        slots: dict[int, str] = {}
        last = -1
        for b in sorted(col, key=lambda b: b.y0):
            lines = _fmt_lines(b)
            n = max(1, len(lines))
            for i, ln in enumerate(lines):
                cy = b.y0 + (i + 0.5) * b.h / n
                s = max(int((cy - base) / lh), last + 1)
                slots[s] = ln
                last = s
        cells.append(slots)

    widths = [max((len(t) for t in c.values()), default=0) for c in cells]
    col_x0 = [min(b.x0 for b in col) for col in band.cols]
    pos = [0]
    for i in range(1, len(cells)):
        want = round((col_x0[i] - col_x0[0]) / cpx)
        pos.append(max(want, pos[i - 1] + widths[i - 1] + MIN_COL_GAP))

    n_rows = max((max(c) for c in cells if c), default=-1) + 1
    lines: list[str] = []
    for r in range(n_rows):
        line = ""
        for i, c in enumerate(cells):
            txt = c.get(r, "")
            if txt:
                line = line.ljust(pos[i]) + txt
        if line.strip():
            lines.append(line.rstrip())
    return lines


def _render_band(band: Band) -> list[str]:
    blk = band.single
    if blk is not None and blk.kind == "table":
        return _table_md(blk.text)
    body = _fmt_lines(blk) if blk is not None else _render_columns(band)
    prefix = "\t" * band.indent
    return [prefix + ln for ln in body]


def _is_verse_pair(a: Band, b: Band, cw: float) -> bool:
    x, y = a.single, b.single
    if x is None or y is None or x.kind != "text" or y.kind != "text":
        return False
    if x.label.get("h") or y.label.get("h") or x.label.get("quote") or y.label.get("quote"):
        return False
    if a.indent != b.indent or x.align != y.align:
        return False
    if x.w > 0.6 * cw or y.w > 0.6 * cw:
        return False
    return (y.y0 - x.y1) <= 0.6 * min(x.h, y.h)


def render_page(page: Page, bands: list[Band]) -> str:
    cw = max(1.0, page.right - page.margin)
    out: list[str] = []
    prev: Band | None = None
    for band in bands:
        lines = _render_band(band)
        if not lines:
            continue
        if prev is not None:
            out.append("\n" if _is_verse_pair(prev, band, cw) else "\n\n")
        out.append("\n".join(lines))
        prev = band
    return "".join(out)


# ---------------------------------------------------------------- IR generation
async def generate_ir(result: dict) -> dict | None:
    """Generate IR from OCR result via LLM. Returns IR dict or None on failure."""
    try:
        ir_dict = await llm_ir(result)
        validate_ir(ir_dict, result)
        return ir_dict
    except (LLMError, IRValidationError) as exc:
        logger.warning("IR generation failed: %s", exc)
        return None


# ---------------------------------------------------------------- main API
async def build_md(
    result: dict, use_llm: bool = True, ir_sink: dict | None = None
) -> str:
    """Build markdown from OCR result.

    1. use_llm=True → LLM → IR → validate → render
    2. Fallback → heuristic geometry-aware

    ir_sink: optional dict filled with the validated IR on the LLM path —
    auto-gen reuses that single IR for job.ir_json (no extra LLM call).
    """
    if use_llm:
        try:
            ir_dict = await llm_ir(result)
            ir_doc = validate_ir(ir_dict, result)
            if ir_sink is not None:
                ir_sink.update(ir_dict)
            return await llm_render_md(ir_doc, result)
        except (LLMError, IRValidationError) as exc:
            logger.warning("LLM IR failed, using heuristic fallback: %s", exc)

    # Heuristic fallback
    pages = extract_pages(result)
    page_bands = [(pg, analyze(pg)) for pg in pages]

    labels = heuristic_labels(pages)
    for pg in pages:
        for b in pg.blocks:
            b.label = labels.get(b.id, {})

    rendered = []
    for pg, bands in page_bands:
        text = render_page(pg, bands)
        if text:
            rendered.append(text)
    return "\n\n".join(rendered)
