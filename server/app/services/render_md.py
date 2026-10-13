"""render_md: OCR result → Markdown via LLM IR or heuristic fallback.

Flow:
  1. use_llm=True → LLM (space-bunny) → IR JSON → validate_ir() → render MD
  2. Fallback (LLM down / use_llm=False) → heuristic geometry-aware

Heuristic fallback copied from llm_md.py: _build_bands, _cluster_columns,
_render_band, _indent_of, _same_cluster.
"""

from __future__ import annotations

import asyncio
import base64
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
from app.core.schemas import IMAGE_MARKER
from app.services.ir import DocumentIR, IR_PROMPT, validate_ir, IRValidationError
from app.services.runtime_settings import get_runtime_setting

# marker template prefix ("**[Hình ảnh chưa trích xuất: vùng ") — dùng để
# quét marker trong md render (embed_crop_urls)
IMAGE_MARKER_PREFIX = IMAGE_MARKER.split("{region_id}")[0]

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
    # cells-shape (kernel parse table 1 lần) — heuristic render pipe MD từ
    # cells (colspan lặp, mirror kernel) thay vì parse lại html.
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


# ---------------------------------------------------------------- extract
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
            # wave-3: cells-shape (kernel parse table) → table; _table_md cần
            # HTML nên text ưu tiên html (nguồn sự thật) khi có. cells giữ trên
            # Block — heuristic render pipe từ cells (colspan lặp, mirror kernel)
            # thay html → server md giống kernel md.
            cells = region.get("cells")
            if cells or "<table" in text.lower():
                kind = "table"
                text = region.get("html") or text
            elif is_image:
                kind = "image"
            else:
                kind = "text"
            blocks.append(Block(rid, pi, kind, tuple(bbox), text, cells=cells))
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
    timeout = await get_runtime_setting(SessionLocal, "llm_timeout", settings.llm_timeout)
    return base_url, model, api_key, timeout


async def _chat(user_content: str, json_mode: bool = True) -> str:
    base_url, model, api_key, timeout = await _llm_config()
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0,
    }
    # json_mode=False (render md): KHÔNG gửi response_format — json_object
    # ép model echo IR/bọc envelope thay vì markdown thô.
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            started = time.perf_counter()
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
    "Empty zones (header/content/footer = []) → render NOTHING for that zone; "
    "do NOT invent content for missing zones. A page may have only content, "
    "only header+content, etc.\n"
    "Output raw markdown only (no code fences).\n"
    "Output raw only — do NOT wrap in JSON.\n\n"
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
    raw = await _chat(content, json_mode=False)
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    if not text:
        raise LLMError("LLM render trả về rỗng")
    # Model free thường bọc markdown trong JSON envelope {"output": ...}
    # hoặc echo IR JSON → unwrap field; thiếu/parsing fail → LLMError →
    # heuristic (markdown thô KHÔNG bao giờ bắt đầu bằng {).
    if text.startswith("{"):
        text = _unwrap_envelope(text, ("output", "markdown")).strip()
        if not text:
            raise LLMError("LLM render trả về rỗng")
    return text




# ---------------------------------------------------------------- render from heuristic
def _fmt_lines(b: Block) -> list[str]:
    lab = b.label
    # P1-R4a/R5: image node text rỗng → marker (ảnh sống sót qua md fallback)
    if b.kind == "image" and not b.text.strip():
        return [IMAGE_MARKER.format(region_id=b.id)]
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


def _cells_md(cells: list) -> list[str]:
    """cells-shape → GFM pipe table (mirror kernel _table_cells_to_md): hàng
    có th (hoặc hàng đầu) = header + separator; colspan → lặp text ô."""
    if not cells:
        return []
    h = next((i for i, r in enumerate(cells) if any(c.get("header") for c in r)), 0)

    def texts(row: list) -> list[str]:
        out: list[str] = []
        for c in row:
            t = str(c.get("text") or "").replace("|", "\\|")
            out.extend([t] * max(1, int(c.get("colspan") or 1)))
        return out

    ht = texts(cells[h])
    lines = ["| " + " | ".join(ht) + " |", "| " + " | ".join(["---"] * len(ht)) + " |"]
    lines += ["| " + " | ".join(texts(r)) + " |" for i, r in enumerate(cells) if i != h]
    return lines

def _render_band(band: Band) -> list[str]:
    blk = band.single
    if blk is not None and blk.kind == "table":
        return _cells_md(blk.cells) if blk.cells else _table_md(blk.text)
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


# ---------------------------------------------------------------- crop embed (WS-PIPE)
CROP_PRESIGN_EXPIRES = 86400

async def embed_crop_keys(
    markdown: str, job_id: int, storage, crop_loader=None
) -> str:
    """RENDER-time: IMAGE_MARKER → `![vùng {rid}](crops/{rid}.png)` RELATIVE
    key khi crop artifact tồn tại; THIẾU → crop_loader on-demand (bytes) →
    data-URI (self-contained, không phụ thuộc URL hết hạn); loader None/lỗi
    → giữ marker. Artifact KHÔNG chứa URL presigned (24h hết hạn → link chết);
    serve-time re-embed qua embed_crop_urls.

    crop_loader: async (rid) → bytes | None — caller wire logic crop on-demand
    (route /regions/{rid}/crop: get_or_make_crop + storage.get)."""
    for m in re.finditer(re.escape(IMAGE_MARKER_PREFIX) + r"([^\]]+)\]\*\*", markdown):
        rid = m.group(1)
        if not await storage.exists(f"exports/{job_id}/crops/{rid}.png"):
            if crop_loader is None:
                continue
            try:
                data = await crop_loader(rid)
            except Exception as exc:  # partial-fail: crop thiếu → giữ marker
                logger.info("on-demand crop job=%s rid=%s failed: %r", job_id, rid, exc)
                continue
            if not data:
                continue
            mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            b64 = base64.b64encode(data).decode("ascii")
            markdown = markdown.replace(
                m.group(0), f"![vùng {rid}](data:{mime};base64,{b64})"
            )
            continue
        markdown = markdown.replace(m.group(0), f"![vùng {rid}](crops/{rid}.png)")
    return markdown

_CROP_REL_RE = re.compile(r"!\[vùng ([^\]]+)\]\(crops/([^\)]+)\)")

async def embed_crop_urls(markdown: str, job_id: int, storage) -> str:
    """SERVE-time (download md-layout): relative `crops/{f}` → presigned 24h
    FRESH mỗi lần serve — URL trong artifact không bao giờ cache."""
    for m in _CROP_REL_RE.finditer(markdown):
        rid, fname = m.group(1), m.group(2)
        url = await storage.presign_get(
            f"exports/{job_id}/crops/{fname}", CROP_PRESIGN_EXPIRES
        )
        markdown = markdown.replace(m.group(0), f"![vùng {rid}]({url})")
    return markdown

# ---------------------------------------------------------------- main API
# tỉ lệ heuristic fallback / tổng lần build — quan sát model free echo/envelope
_FALLBACK_STATS = {"fallback": 0, "total": 0}


def _log_fallback(exc: Exception) -> None:
    _FALLBACK_STATS["fallback"] += 1
    logger.warning(
        "HEURISTIC FALLBACK %s — tỉ lệ %d/%d",
        type(exc).__name__, _FALLBACK_STATS["fallback"], _FALLBACK_STATS["total"],
    )

async def build_md(
    result: dict, use_llm: bool = True, ir_sink: dict | None = None
) -> str:
    """Build markdown from OCR result.

    1. use_llm=True → LLM → IR → validate → render
    2. Fallback → heuristic geometry-aware

    ir_sink: optional dict filled with the validated IR on the LLM path —
    auto-gen reuses that single IR for job.ir_json (no extra LLM call).
    """
    _FALLBACK_STATS["total"] += 1
    if use_llm:
        try:
            ir_dict = await llm_ir(result)
            ir_doc = validate_ir(ir_dict, result)
            if ir_sink is not None:
                ir_sink.update(ir_dict)
            return await llm_render_md(ir_doc, result)
        except (LLMError, IRValidationError) as exc:
            logger.warning("HEURISTIC FALLBACK render — layout tạm: %r", exc)
            _log_fallback(exc)

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
