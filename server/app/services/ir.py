"""Document IR: Pydantic models + validator.

IR = intermediate representation between OCR and renderer.
LLM classifies structure (type/role), never rewrites OCR text.
source_block_ids map back to OCR block IDs for traceability.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


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
    id: str
    type: NodeType
    role: str = "unknown"
    text: str = ""
    align: Literal["left", "center", "right", "justify", "unknown"] = "unknown"
    indent: int = 0
    source_block_ids: list[str] = Field(default_factory=list)
    children: list["NodeIR"] = Field(default_factory=list)


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


def _collect_ocr_block_ids(ocr_result: dict) -> set[str]:
    """All block IDs across all pages in OCR result."""
    ids: set[str] = set()
    for page in ocr_result.get("pages", []):
        for region in page.get("regions", []):
            rid = str(region.get("id"))
            if rid:
                ids.add(rid)
    return ids


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


def validate_ir(ir: dict, ocr_result: dict) -> DocumentIR:
    """Validate IR dict against OCR result → DocumentIR.

    Raises IRValidationError on any violation.
    """
    try:
        doc = DocumentIR.model_validate(ir)
    except Exception as exc:
        raise IRValidationError(f"IR schema invalid: {exc}") from exc

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
    for page in doc.pages:
        _check_source_ids(page.header, valid_ocr_ids)
        _check_source_ids(page.content, valid_ocr_ids)
        _check_source_ids(page.footer, valid_ocr_ids)

    # Check page_number >= 1
    for page in doc.pages:
        if page.page_number < 1:
            raise IRValidationError(f"page_number phải >= 1: {page.page_number}")

    return doc
