"""Document IR: Pydantic models + validator.

IR = intermediate representation between OCR and renderer.
LLM classifies structure (type/role), never rewrites OCR text.
source_block_ids map back to OCR block IDs for traceability.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

IR_PROMPT = (
    "You are a document structure analyzer. Given OCR output (blocks with bbox, text), "
    "produce a Document IR following this schema:\n"
    '{"document_id": "...", "schema_version": "1.0", "pages": [{"page_id": "...", "page_number": 1, "header": [], "content": [], "footer": []}]}\n\n'
    "Rules:\n"
    "- COVERAGE: every OCR block id must appear in exactly one node's source_block_ids "
    "(root or child). Never drop a block, never reuse a block in two nodes.\n"
    "- GEOMETRY FIRST: group blocks by bbox BEFORE considering type — blocks with "
    "overlapping y-range and disjoint x-range on the same page = parallel columns "
    "(read left→right within each row band); blocks forming a regular grid (aligned "
    "rows × columns) = table; sequential blocks with hanging indent or bullet/letter "
    "markers = list; first block of a band = heading; image blocks = figure nodes "
    "(keep, never drop).\n"
    "- type is only used to LABEL the node AFTER geometry grouping. "
    "Full type set: heading (level1..N by position/size), paragraph, list, poem, "
    "table, figure, caption, formula, quote, footnote, page_number, form_field, "
    "separator, unknown.\n"
    "- header: page heading blocks at top of page (y0 < 15% page height): logo, institution, "
    "exam title.\n"
    "- footer: only page furniture at the bottom: page numbers, form fields (name/id boxes), "
    "separators. If a bottom block is normal reading content (verse line, paragraph, citation), "
    "keep it in content with its group.\n"
    "- content: everything else\n"
    "- type: MUST be exactly one of: heading, paragraph, list, poem, table, figure, caption, "
    "formula, quote, footnote, page_number, form_field, separator, unknown. "
    "CLOSED SET — NEVER invent new types (e.g. 'note', 'text', 'title'). "
    "A block matching none of these → type='unknown'. "
    "Role words (citation, passage, line, instruction, ...) belong in role, NEVER in type.\n"
    "- role: document_title, section_heading, running_header, running_footer, question, answer, "
    "passage, line, citation, instruction, prompt, form_field, ...\n"
    "- source_block_ids: map to OCR block IDs (p1_b0, p1_b1, ...)\n"
    "- bbox: [x1, y1, x2, y2] per node, from OCR block bbox; "
    "many source_block_ids → union (x1=min, y1=min, x2=max, y2=max)\n"
    "- children: group related blocks — a poem node contains ALL its consecutive verse lines "
    "as children; a list node contains ALL its items (a., b., c., ...). The source note/citation "
    "after a poem or passage is a separate node, never a poem line.\n"
    "- merge only blocks that are continuations of the same sentence/paragraph; never merge "
    "unrelated blocks (e.g. an instruction line) into a citation node.\n\n"
    "OCR output:\n{ocr_json}"
)


class NodeType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    POEM = "poem"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FORMULA = "formula"
    QUOTE = "quote"
    FOOTNOTE = "footnote"
    PAGE_NUMBER = "page_number"
    FORM_FIELD = "form_field"
    SEPARATOR = "separator"
    UNKNOWN = "unknown"


class NodeIR(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # id optional: program auto-assign khi LLM thiếu (spec: id do program assign),
    # chấp nhận cả "node_id" alias vì LLM hay ghi sai tên field.
    id: str = Field(default="", validation_alias=AliasChoices("id", "node_id"))
    type: NodeType
    role: str = "unknown"
    text: str = ""
    align: Literal["left", "center", "right", "justify", "unknown"] = "unknown"
    indent: int = 0
    source_block_ids: list[str] = Field(default_factory=list)
    bbox: list[int] | None = None
    children: list["NodeIR"] = Field(default_factory=list)

    @field_validator("bbox")
    @classmethod
    def _bbox_shape(cls, v: list[int] | None) -> list[int] | None:
        # spec §4: bbox là [x1, y1, x2, y2]; Plan D PIL-crops cần len==4.
        if v is not None and len(v) != 4:
            raise ValueError("bbox phải có đúng 4 phần tử [x1, y1, x2, y2].")
        return v


class PageIR(BaseModel):
    page_id: str
    page_number: int
    header: list[NodeIR] = Field(default_factory=list)
    content: list[NodeIR] = Field(default_factory=list)
    footer: list[NodeIR] = Field(default_factory=list)


class DocumentIR(BaseModel):
    document_id: str
    schema_version: str = "1.0"
    pages: list[PageIR] = Field(default_factory=list)


class IRValidationError(Exception):
    """IR fails validation (caller → fallback or 502)."""


def _collect_ocr_block_ids(ocr_result: dict, *, skip_image: bool = False) -> set[str]:
    """All block IDs across all pages in OCR result.

    skip_image: bỏ image region — dùng cho coverage set (P1-R4b: LLM không
    bắt buộc cover ảnh, prompt không đổi); source-id check vẫn nhận image id
    (valid set đầy đủ riêng). P2-1: exempt CHỈ verdict=image_unextractable —
    placeholder-OR đã bỏ: LLM mislabel text→image (placeholder=True, verdict
    khác) không được thoát coverage (mất text)."""
    ids: set[str] = set()
    for page in ocr_result.get("pages", []):
        for region in page.get("regions", []):
            rid = str(region.get("id"))
            if skip_image and region.get("verdict") == "image_unextractable":
                continue
            if rid:
                ids.add(rid)
    return ids


def _block_bbox(ocr_result: dict, block_id: str) -> list[int] | None:
    for page in ocr_result.get("pages", []):
        for region in page.get("regions", []):
            if str(region.get("id")) == block_id:
                bbox = region.get("bbox")
                if bbox and len(bbox) == 4:
                    return list(bbox)
    return None

def _union_bbox(ocr_result: dict, block_ids: list[str]) -> list[int] | None:
    """Union nhiều block bbox: x1=min, y1=min, x2=max, y2=max."""
    boxes = [b for bid in block_ids if (b := _block_bbox(ocr_result, bid)) is not None]
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    ]

def _block_text(ocr_result: dict, block_id: str) -> str:
    for page in ocr_result.get("pages", []):
        for region in page.get("regions", []):
            if str(region.get("id")) == block_id:
                return (region.get("text") or "").strip()
    return ""

def _fill_bbox(nodes: list[NodeIR], ocr_result: dict) -> None:
    """LLM bỏ trống bbox → union từ source_block_ids.

    Renderer dùng node.bbox trực tiếp, không cần lookup OCR result.
    """
    for node in nodes:
        if node.bbox is None:
            node.bbox = _union_bbox(ocr_result, node.source_block_ids)
        if node.children:
            _fill_bbox(node.children, ocr_result)

def _fill_text(nodes: list[NodeIR], ocr_result: dict) -> None:
    """LLM structurize KHÔNG viết lại text (spec) → node.text luôn rỗng.
    Renderer (LLM render) cần text thật → join text từ OCR qua
    source_block_ids. Giống _fill_bbox: populate từ nguồn, không sửa LLM.
    """
    for node in nodes:
        if not node.text:
            parts = [t for bid in node.source_block_ids
                     if (t := _block_text(ocr_result, bid))]
            node.text = "\n".join(parts)
        if node.children:
            _fill_text(node.children, ocr_result)

def _assign_missing_ids(nodes: list[NodeIR], counter: list[int]) -> None:
    """LLM thiếu id/node_id → auto-assign (spec: id do program assign)."""
    for node in nodes:
        if not node.id:
            counter[0] += 1
            node.id = f"auto_n{counter[0]}"
        if node.children:
            _assign_missing_ids(node.children, counter)

def _check_unique_ids(nodes: list[NodeIR], seen: set[str], path: str = "") -> None:
    """Recursively check all node IDs are unique across the document."""
    for node in nodes:
        if node.id in seen:
            raise IRValidationError(f"ID không unique: {node.id} tại {path}")
        seen.add(node.id)
        if node.children:
            _check_unique_ids(node.children, seen, f"{path}/{node.id}")


def _check_no_cycles(nodes: list[NodeIR], ancestors: set[str] | None = None) -> None:
    """Detect cycles in children graph."""
    if ancestors is None:
        ancestors = set()
    for node in nodes:
        if node.id in ancestors:
            raise IRValidationError(f"Cycle tại node: {node.id}")
        if node.children:
            _check_no_cycles(node.children, ancestors | {node.id})


def _check_source_ids(nodes: list[NodeIR], valid_ids: set[str]) -> None:
    """All source_block_ids must exist in OCR result."""
    for node in nodes:
        for bid in node.source_block_ids:
            if bid not in valid_ids:
                raise IRValidationError(
                    f"source_block_ids không tồn tại trong OCR: {bid} (node {node.id})"
                )
        if node.children:
            _check_source_ids(node.children, valid_ids)

def _collect_source_ids(nodes: list[NodeIR], out: list[str]) -> None:
    """Every source_block_id qua mọi node (kể cả children) — coverage check."""
    for node in nodes:
        out.extend(node.source_block_ids)
        if node.children:
            _collect_source_ids(node.children, out)

def _check_coverage(ir: DocumentIR, valid_ids: set[str]) -> None:
    """P0-B: mỗi OCR region phải được dùng exactly-once — LLM bỏ block =
    mất chữ im im, render fallback heuristic. Thiếu/trùng → raise, nêu id."""
    used: list[str] = []
    for page in ir.pages:
        _collect_source_ids(page.header, used)
        _collect_source_ids(page.content, used)
        _collect_source_ids(page.footer, used)
    counts: dict[str, int] = {}
    for bid in used:
        counts[bid] = counts.get(bid, 0) + 1
    missing = sorted(valid_ids - counts.keys())
    duplicated = sorted(b for b, n in counts.items() if n > 1)
    if missing or duplicated:
        parts = []
        if missing:
            parts.append(f"thiếu (OCR region không được dùng): {', '.join(missing)}")
        if duplicated:
            parts.append(f"trùng (dùng >1 lần): {', '.join(duplicated)}")
        raise IRValidationError("Coverage sai — " + "; ".join(parts))


def _ocr_regions_by_id(ocr_result: dict) -> dict:
    return {
        r["id"]: r
        for pg in ocr_result.get("pages", [])
        for r in pg.get("regions", [])
    }

def _is_table_region(regions: dict, node: NodeIR) -> bool:
    """S4: lookup source_block_ids → OCR region có <table/cells (render_md pattern)."""
    for bid in node.source_block_ids:
        region = regions.get(bid)
        if region is None:
            continue
        text = region.get("text") or ""
        if region.get("cells") or "<table" in text.lower():
            return True
    return False

def _warn_cross_column(ir: DocumentIR, ocr_result: dict) -> None:
    """S4 warn-only: cùng y-band + 2 cột x-disjoint + khác type + không bảng
    → warning log (fail đã có heuristic fallback — warning giữ signal)."""
    regions = _ocr_regions_by_id(ocr_result)
    for page in ir.pages:
        nodes = [n for n in page.content if n.bbox is not None]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                ha = a.bbox[3] - a.bbox[1]
                hb = b.bbox[3] - b.bbox[1]
                tol = max(10, 0.3 * max(ha, hb))
                if abs(a.bbox[1] - b.bbox[1]) > tol:
                    continue  # không cùng y-band
                ax = sorted((a.bbox[0], a.bbox[2]))
                bx = sorted((b.bbox[0], b.bbox[2]))
                if not (ax[1] <= bx[0] or bx[1] <= ax[0]):
                    continue  # x overlap → cùng cột, không phải 2 cột
                if a.type == b.type:
                    continue
                if _is_table_region(regions, a) or _is_table_region(regions, b):
                    continue  # bảng = ngoại lệ
                logger.warning(
                    "cross-column type mismatch page=%s: %s(%s) vs %s(%s) "
                    "cùng y-band, 2 cột, không bảng",
                    page.page_number, a.id, a.type, b.id, b.type,
                )

def _sanitize_ir_types(ir: dict) -> dict:
    """IR-NOTE: LLM thỉnh thoảng bịa type ngoài enum (VD 'note' — dev job5) →
    pydantic reject kill cả document → heuristic fallback → ir_json NULL.
    Sanitize guard: type lạ → 'unknown' + warning per-node, 1 node sai không kill document."""
    valid = {t.value for t in NodeType}

    def walk(nodes: list) -> None:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get("type") not in valid:
                logger.warning("IR type lạ %r → unknown (node %s)", n.get("type"), n.get("id"))
                n["type"] = "unknown"
            walk(n.get("children") or [])

    for page in ir.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for section in ("header", "content", "footer"):
            walk(page.get(section) or [])
    return ir

def validate_ir(ir: dict, ocr_result: dict) -> DocumentIR:
    """Validate IR dict against OCR result → DocumentIR.

    Raises IRValidationError on any violation.
    """
    ir = _sanitize_ir_types(ir)
    try:
        doc = DocumentIR.model_validate(ir)
    except Exception as exc:
        raise IRValidationError(f"IR schema invalid: {exc}") from exc

    # Auto-assign id cho node thiếu id (trước unique check)
    counter = [0]
    for page in doc.pages:
        _assign_missing_ids(page.header, counter)
        _assign_missing_ids(page.content, counter)
        _assign_missing_ids(page.footer, counter)

    # Collect all node IDs across all pages/sections
    all_ids: set[str] = set()
    for page in doc.pages:
        _check_unique_ids(page.header, all_ids, f"page_{page.page_id}/header")
        _check_unique_ids(page.content, all_ids, f"page_{page.page_id}/content")
        _check_unique_ids(page.footer, all_ids, f"page_{page.page_id}/footer")

    # Check cycles
    for page in doc.pages:
        _check_no_cycles(page.header)
        _check_no_cycles(page.content)
        _check_no_cycles(page.footer)

    # Check source_block_ids exist in OCR
    valid_ocr_ids = _collect_ocr_block_ids(ocr_result)
    # P1-R4b: coverage bỏ image region — LLM không bắt buộc cover ảnh
    coverage_ids = _collect_ocr_block_ids(ocr_result, skip_image=True)
    # bbox: LLM gán hoặc union từ source_block_ids (renderer dùng trực tiếp)
    # text: LLM không viết lại text → join từ OCR qua source_block_ids (render cần)
    for page in doc.pages:
        _fill_bbox(page.header, ocr_result)
        _fill_bbox(page.content, ocr_result)
        _fill_bbox(page.footer, ocr_result)
        _fill_text(page.header, ocr_result)
        _fill_text(page.content, ocr_result)
        _fill_text(page.footer, ocr_result)
    # S4: warn-only cross-column check (sau _fill_bbox — bbox đã đầy đủ)
    _warn_cross_column(doc, ocr_result)
    for page in doc.pages:
        _check_source_ids(page.header, valid_ocr_ids)
        _check_source_ids(page.content, valid_ocr_ids)
        _check_source_ids(page.footer, valid_ocr_ids)
    # P0-B: coverage — mọi OCR id exactly-once (thiếu = mất chữ, trùng = lặp);
    # image region loại khỏi bắt buộc (coverage_ids) — LLM không cover cũng OK
    _check_coverage(doc, coverage_ids)

    # Check page_number >= 1
    for page in doc.pages:
        if page.page_number < 1:
            raise IRValidationError(f"page_number phải >= 1: {page.page_number}")

    return doc


# --- S3: heading anchors ≠ header trang (Lane S Task 4) ---

@dataclass
class AnchorState:
    """Doc-level §counter + open-section stack — carry xuyên trang."""
    counter: int = 0
    stack: list = field(default_factory=list)
    # child index theo parent path — sibling đếm liên tục, không reset trang
    child_counts: dict = field(default_factory=dict)

# đầu block: "1.", "1)", "1.1.1" (số cuối block) ...; whitespace bắt buộc sau
# separator — "1)Foo" negative; "2024." bắt 4-digit year guard phía dưới
_HEADING_ANCHOR_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:[.)]\s|\s|$)")

def _anchor_label(state: AnchorState, level: int) -> str:
    """Cấp k = depth k trong stack; không nhảy cấp; numbering liên tục."""
    if level == 1:
        state.counter += 1
        state.stack = [state.counter]
    else:
        level = min(level, len(state.stack) + 1)  # clamp nhảy cóc cấp
        key = tuple(state.stack[: level - 1])
        n = state.child_counts.get(key, 0) + 1
        state.child_counts[key] = n
        state.stack = state.stack[: level - 1] + [n]
    return "§" + ".".join(str(n) for n in state.stack)

def extract_heading_anchors(
    pages: list[dict], state: AnchorState | None = None
) -> tuple[list[dict], AnchorState]:
    """OCR pages → heading annotations + state.

    Positive: "1. Benefit", "1) Foo" (whitespace sau [.)] bắt buộc), "1.1.1",
    "   2.2 Indent". Negative: "2024. Năm" (4-digit guard), "Câu 1:",
    "Bài 2", "abc 1. x" (regex anchored đầu block).
    Header y-band 15% top + không số → type header/doc_title, không tham
    gia §index. Số thứ tự document-level (counter carry xuyên trang).
    """
    state = state or AnchorState()
    out: list[dict] = []
    for pi, pg in enumerate(pages):
        h = float(pg.get("height") or 0)
        regions = sorted(
            pg.get("regions", []), key=lambda r: (r.get("bbox") or [0, 0])[1]
        )
        for ri, region in enumerate(regions):
            text = region.get("text") or ""
            m = _HEADING_ANCHOR_RE.match(text)
            num = m.group(1) if m else ""
            is_year = bool(num) and "." not in num and len(num) == 4
            y0 = (region.get("bbox") or [0, 0])[1]
            if m and not is_year:
                level = num.count(".") + 1
                out.append({
                    "block_id": region["id"],
                    "type": "heading",
                    "label": _anchor_label(state, level),
                    "level": level,
                })
            elif h and y0 < 0.15 * h:
                out.append({
                    "block_id": region["id"],
                    "type": "doc_title" if (pi == 0 and ri == 0) else "header",
                })
    return out, state


# --- S2: IR per-page sequential — shared 2 path, DI chat_fn (Lane S Task 5) ---

MAX_IR_PAGE_CALLS = 20

class IRPageError(Exception):
    """Per-page IR prompt/parse/merge failure → LLMError → heuristic fallback."""

IR_PROMPT_PAGE = (
    "You are a document structure analyzer. Analyze ONE page of OCR output "
    "into a Document IR page object (same node schema as document IR): "
    '{"page_id": "...", "page_number": N, "header": [], "content": [], "footer": []}\n'
    "Rules (same as full document IR): geometry first (columns/tables/lists by "
    "bbox), type labels the grouping AFTER, source_block_ids map to THIS page's "
    "OCR block ids, bbox [x1,y1,x2,y2] from OCR, children group related blocks. "
    "Never rewrite OCR text.\n"
    # S4: cross-column normalize — cùng y-band + 2 cột → ép cùng type/level;
    # block bảng (OCR text chứa <table hoặc cells grid) = ngoại lệ
    # IR-NOTE (bug job5): LLM bịa type='note' → enum reject → ir_json NULL.
    # Ép closed set 1-1 với NodeType (test assert), unknown khi không khớp.
    "- type: MUST be exactly one of: heading, paragraph, list, poem, table, figure, caption, "
    "formula, quote, footnote, page_number, form_field, separator, unknown. "
    "CLOSED SET — NEVER invent new types (e.g. 'note', 'text', 'title'). "
    "A block matching none of these → type='unknown'.\n"
    "- CROSS-COLUMN: blocks sharing the same y-band in 2 side-by-side columns "
    "MUST get the SAME type and heading level (read left→right); EXCEPTION: "
    "table blocks (OCR text contains <table or a cells grid) keep type table.\n"
    # S3: header y-band 15% + §anchor instruction
    "- Header trang = top 15% y-band WITHOUT a leading sequence number "
    "(e.g. '1.' / '1)') → role running_header / doc_title, NEVER type heading.\n"
    "- HEADING ANCHORS: numbered headings ('1.', '1.1)') are §sections — "
    "assign §labels in document order across pages using the running §context "
    "below; numbering stays continuous, never restarts per page.\n"
    "Running §context — headings already seen in EARLIER pages (keep continuity, "
    "do NOT restart numbering):\n{running_ctx}\n\n"
    "OCR output of this page:\n{ocr_json}"
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

def _parse_ir_json(text: str, what: str) -> dict:
    """LLM raw → first JSON object (fence strip + raw_decode)."""
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    start = text.find("{")
    if start == -1:
        raise IRPageError(f"{what}: không chứa JSON object")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except (ValueError, TypeError) as exc:
        raise IRPageError(f"{what}: không phải JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise IRPageError(f"{what}: không phải JSON object")
    return obj

async def _ir_page(page_ocr: dict, running_ctx: str, chat_fn) -> dict:
    """1 trang OCR → PageIR dict. KHÔNG import httpx — chat_fn là DI seam."""
    content = (
        IR_PROMPT_PAGE
        .replace("{running_ctx}", running_ctx or "(trống)")
        .replace("{ocr_json}", json.dumps(page_ocr, ensure_ascii=False))
    )
    return _parse_ir_json(await chat_fn(content), "IR trang")

async def _ir_full(result: dict, chat_fn) -> dict:
    """Legacy IR_PROMPT full-result 1-call (degrade/cost-cap path, giữ nguyên)."""
    content = IR_PROMPT.replace("{ocr_json}", json.dumps(result, ensure_ascii=False))
    return _parse_ir_json(await chat_fn(content), "IR đầy đủ")

def _ctx_from_page(page_ocr: dict, state: AnchorState) -> tuple[str, AnchorState]:
    """§labels + text heading trang này → running context (state carry)."""
    anns, state = extract_heading_anchors([page_ocr], state)
    texts = {
        r["id"]: (r.get("text") or "").strip() for r in page_ocr.get("regions", [])
    }
    lines = [
        f"{a['label']} {texts.get(a['block_id'], '')}".rstrip()
        for a in anns if a["type"] == "heading"
    ]
    return "\n".join(lines), state

async def llm_ir_pages(result: dict, chat_fn) -> dict:
    """S2: sequential per-page IR — render_md.llm_ir + render_docx.llm_ir delegate.

    > MAX_IR_PAGE_CALLS trang → degrade 1-call full-result (cost cap, tránh
    N×180s). Page fail → retry 1 → still fail → degrade full-result. Merge:
    sort page_number, trùng → IRPageError (→ LLMError → heuristic fallback).
    """
    pages = list(result.get("pages") or [])
    if len(pages) > MAX_IR_PAGE_CALLS:
        logger.warning(
            "IR per-page: %d trang > %d — degrade 1-call full-result",
            len(pages), MAX_IR_PAGE_CALLS,
        )
        return await _ir_full(result, chat_fn)
    page_irs: list[dict] = []
    state = AnchorState()
    running_ctx = ""
    for pi, page in enumerate(pages):
        for attempt in range(2):
            try:
                page_ir = await _ir_page(page, running_ctx, chat_fn)
                break
            except Exception as exc:  # retry 1 → fail → degrade full-result
                if attempt:
                    logger.warning(
                        "IR per-page: trang %d fail sau retry — fallback full-result: %r",
                        pi + 1, exc,
                    )
                    return await _ir_full(result, chat_fn)
                logger.warning("IR per-page: trang %d fail — retry 1: %r", pi + 1, exc)
        if "pages" in page_ir:  # model trả full document IR — dùng nguyên
            return page_ir
        if "page_number" not in page_ir:
            page_ir["page_number"] = pi + 1
        page_irs.append(page_ir)
        ctx, state = _ctx_from_page(page, state)
        if ctx:
            running_ctx = (running_ctx + "\n" + ctx).strip()
    numbers = [p["page_number"] for p in page_irs]
    if len(set(numbers)) != len(numbers):
        raise IRPageError(f"page_number trùng khi merge: {numbers}")
    page_irs.sort(key=lambda p: p["page_number"])
    return {"document_id": "doc_001", "schema_version": "1.0", "pages": page_irs}
