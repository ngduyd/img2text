"""Document IR: Pydantic models + validator.

IR = intermediate representation between OCR and renderer.
LLM classifies structure (type/role), never rewrites OCR text.
source_block_ids map back to OCR block IDs for traceability.
"""

from __future__ import annotations

import logging
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
    "- header: page heading blocks at top of page (y0 < 15% page height): logo, institution, "
    "exam title.\n"
    "- footer: only page furniture at the bottom: page numbers, form fields (name/id boxes), "
    "separators. If a bottom block is normal reading content (verse line, paragraph, citation), "
    "keep it in content with its group.\n"
    "- content: everything else\n"
    "- type: MUST be exactly one of: heading, paragraph, list, poem, table, figure, caption, "
    "formula, quote, footnote, page_number, form_field, separator, unknown. "
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


def validate_ir(ir: dict, ocr_result: dict) -> DocumentIR:
    """Validate IR dict against OCR result → DocumentIR.

    Raises IRValidationError on any violation.
    """
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
