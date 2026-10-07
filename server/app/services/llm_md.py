"""Plan D5: LLM → md-layout (geometry-aware markdown) export.

Flow: result blocks (id/type/bbox/text VERBATIM, no truncation) → POST
{LLM_BASE_URL}/chat/completions (model, temperature 0, response_format
json_object; one retry — a rejected response_format is dropped on retry)
→ JSON {"markdown": "..."} → content validation: format markers stripped
from BOTH the LLM output and the source texts must yield the same word
MULTISET (word-multiset check — LLM may add md syntax or RE-ORDER words
for layout, never touch the words themselves)
→ markdown string. LLMMdError = unreachable/unparsable; LLMMdContentError
= LLM altered block content. Routes map both to 502 and never cache.
"""

import json
import logging
import re
import time
from collections import Counter

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# HTML table cells in source text (batch ingest keeps them verbatim)
_TABLE_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_HR_RE = re.compile(r"[-*_]+$")

PROMPT_INSTRUCTION = (
    'Bạn là chuyên gia dựng bố cục Markdown. INPUT là JSON {"blocks": '
    "[{id, page, type, bbox, text}]} từ OCR; text là NGUYÊN VĂN. Trả về "
    'JSON {"markdown": "..."} vẽ lại layout bằng markdown:\n'
    "1. type=table → bảng markdown bằng '| ... |' (dòng '---' phân cách).\n"
    "2. Block không phải table: hai block cùng xmin và xmax (bbox[0], bbox[2]) "
    "ở vị trí y khác, hoặc hai box bao nhau nhưng cùng inset x (cùng lề "
    "trái-phải) → block cột phải thụt lề bằng TAB đầu dòng.\n"
    "3. Tiêu đề → '# ' hoặc '## ' theo cấp; nhấn mạnh → '**...**'.\n"
    "4. GIỮ NGUYÊN text từng block: không sửa, không lược, không thêm từ; "
    "chỉ dùng '#', '**', TAB, '|', '>' làm định dạng; không bullet, không "
    "'---' (trừ phân cách bảng).\n"
    "Chỉ trả JSON, không kèm gì khác."
)

class LLMMdError(Exception):
    """LLM unreachable / rejected / unparsable markdown (route maps to 502)."""

class LLMMdContentError(Exception):
    """LLM altered block text (route maps to 502 verbatim-content message)."""

def _extract(result: dict) -> list[dict]:
    """Flat non-empty blocks: unique id, type (table HTML / image / text), bbox."""
    blocks: list[dict] = []
    seen: set[str] = set()
    for pi, page in enumerate(result.get("pages", [])):
        for region in page.get("regions", []):
            text = region.get("text") or ""
            if not text.strip():  # empty block → nothing to reproduce
                continue
            rid = str(region.get("id"))
            if rid in seen:  # region ids restart per page → keep unique
                rid = f"p{pi}-{rid}"
            seen.add(rid)
            if "<table" in text.lower():
                kind = "table"
            elif region.get("placeholder") or region.get(
                "verdict"
            ) == "image_unextractable":
                kind = "image"
            else:
                kind = "text"
            blocks.append(
                {"id": rid, "page": pi, "type": kind,
                 "bbox": region.get("bbox"), "text": text}
            )
    return blocks

def _plain(text: str) -> str:
    """Strip md/HTML format markers per line → whitespace-normalized text.

    Symmetric on both sides of the comparison: heading '#', '**' removed
    (no stray space), '\\|' unescaped before pipe-split, leading tab/space,
    '|' (cells split, separators dropped), blockquote '>', HTML tags, hr
    segments (table '---' rows), internal whitespace collapsed per segment.
    """
    out: list[str] = []
    for line in text.splitlines():
        line = line.replace("**", "").replace("\\|", "|")
        for seg in line.split("|"):  # table pipes delimit cells (\| unescaped)
            seg = _TAG_RE.sub(" ", seg).strip()
            while seg.startswith(">"):
                seg = seg[1:].strip()
            seg = re.sub(r"^#{1,6}\s*", "", seg).strip()
            seg = re.sub(r"\s+", " ", seg)  # mid-line collapse (emphasis gap)
            if not seg or _HR_RE.fullmatch(seg):
                continue  # blank / hr / table separator cell
            out.append(seg)
    return " ".join(out)

def _expected(blocks: list[dict]) -> str:
    """Source plain text: table blocks → cell texts (HTML stripped), in order."""
    parts: list[str] = []
    for b in blocks:
        text = b["text"]
        if b["type"] == "table":
            cells = [
                _plain(_TAG_RE.sub(" ", c))
                for c in _TABLE_CELL_RE.findall(text)
            ]
            text = " ".join(c for c in cells if c) or text
        plain = _plain(text)
        if plain:
            parts.append(plain)
    return " ".join(parts)

def _validate(blocks: list[dict], markdown: str) -> None:
    """BUGFIX 1: compare as word MULTISETS, not sequence.

    LLM re-orders header words to center them — same words = PASS; any
    added/removed/duplicated/substituted word still raises (route → 502).
    ponytail: word-multiset check — cho phép re-order cho layout; upgrade
    path: per-block position check nếu cần chống shuffle ngầm.
    """
    expected = Counter(_expected(blocks).split())
    actual = Counter(_plain(markdown).split())
    if expected != actual:
        missing = list((expected - actual).elements())
        extra = list((actual - expected).elements())
        raise LLMMdContentError(
            f"lệch nội dung: thiếu {missing[:20]!r} ≠ dư {extra[:20]!r}"
        )

def _parse(content: str) -> str:
    """Strip optional markdown fence → JSON {"markdown": str}."""
    text = (content or "").strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LLMMdError(f"markdown không phải JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("markdown"), str):
        raise LLMMdError('phản hồi thiếu khóa "markdown"')
    return data["markdown"]

def _log_call(endpoint: str, n_blocks: int, started: float) -> None:
    """One INFO line per LLM POST — never log prompt/content (security)."""
    logger.info(
        "llm called: fmt=md-layout model=%s endpoint=%s blocks=%d elapsed=%.1fs",
        settings.llm_model,
        endpoint,
        n_blocks,
        round(time.perf_counter() - started, 1),
    )

async def _markdown(blocks: list[dict]) -> str:
    """POST chat/completions; 1 retry (drops response_format when rejected)."""
    payload: dict = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT_INSTRUCTION
                + "\n"
                + json.dumps({"blocks": blocks}, ensure_ascii=False),
            }
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = (
        {"Authorization": f"Bearer {settings.llm_api_key}"}
        if settings.llm_api_key
        else {}  # empty key = no auth header (local compatible)
    )
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        for attempt in range(2):
            started = time.perf_counter()
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                _log_call(url, len(blocks), started)  # failed call: still observable
                logger.warning("llm call failed: fmt=md-layout error=%s", exc)
                if attempt:
                    raise LLMMdError(f"LLM không phản hồi: {exc}") from exc
                continue  # retry 1
            _log_call(url, len(blocks), started)
            if resp.status_code < 400:
                try:
                    content = resp.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMMdError(f"phản hồi thiếu content: {exc}") from exc
                return _parse(content)
            logger.warning(
                "md-layout LLM rejected status=%s body=%s",
                resp.status_code,
                resp.text[:200],
            )
            payload.pop("response_format", None)  # server rejected it → retry bare
            if attempt:
                raise LLMMdError(f"LLM HTTP {resp.status_code}")
    raise LLMMdError("LLM không phản hồi")

async def build_md(result: dict) -> str:
    """result.json → validated md-layout markdown string (raises on tamper)."""
    blocks = _extract(result)
    if not blocks:  # nothing to reproduce → no LLM round-trip
        return ""
    markdown = await _markdown(blocks)
    _validate(blocks, markdown)
    return markdown
