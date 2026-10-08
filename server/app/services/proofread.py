"""Plan proofread: LLM đọc text từng trang → gợi ý sửa lỗi OCR (best-effort).

Flow: job.result["pages"] → join regions text (newline) → POST
{LLM_BASE_URL}/chat/completions (model=settings.llm_model, temperature 0,
response_format json_object, Bearer khi LLM_API_KEY có — copy pattern
llm_md) → JSON {"items":[{phrase,reason,suggestion}]} → fuzzy locate
(normalize whitespace + fold diacritics) → OcrSuggestion rows (pending).

Contract: LLM down / phản hồi rác → WARNING + trả 0, KHÔNG fail job
(gợi ý là best-effort; job đã done vẫn done). Mỗi lần chạy thay thế toàn
bộ gợi ý cũ của job. Offset lưu DB là char offsets trong PAGE TEXT —
tham khảo; client replace bằng fuzzy find theo `original` (nội dung editor
≠ page text).

AsyncClient bound at import (from httpx import AsyncClient): tests patch
the module-local seam (conftest stub fails fast; fakes override), the
global fake_llm patches never reach this module.
"""

import json
import logging
import time
import unicodedata

import httpx
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models import Job, OcrSuggestion

logger = logging.getLogger(__name__)

PROMPT = (
    "Đề thi (ngữ cảnh): {hint}\n"
    "Văn bản OCR (có thể lệch):\n{text}\n"
    "Tìm từ/cụm từ bị OCR sai: ký tự lỗi, thiếu dấu, sai ngữ cảnh.\n"
    'Trả JSON: {{"items":[{{"phrase":"...","reason":"...","suggestion":"..."}}]}}\n'
    "Chỉ nghi ngờ thực sự. Không sửa lỗi chính tả bình thường. "
    "Không đổi nội dung đúng."
)

class ProofreadError(Exception):
    """LLM unreachable / rejected / unparsable (caller → warning + 0)."""

def _fold(ch: str) -> str:
    """One char → no-diacritic lowercase (NFD strip combining marks)."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c)
    )
    return stripped.lower()

def _norm_map(text: str, fold: bool) -> tuple[str, list[int]]:
    """Whitespace-collapsed (optionally diacritic-folded) text + offset map.

    pos[i] = original index of emitted char i — collapsed runs map to the
    first whitespace of the run; folded expansions share the source index.
    """
    out: list[str] = []
    pos: list[int] = []
    prev_ws = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_ws:
                continue
            out.append(" ")
            pos.append(i)
            prev_ws = True
            continue
        prev_ws = False
        chars = _fold(ch) if fold else ch
        for c in chars:
            out.append(c)
            pos.append(i)
    return "".join(out), pos

def locate(page_text: str, phrase: str) -> tuple[int, int] | None:
    """Locate phrase in page text → [start, end) original offsets; None = skip.

    Passes: exact → whitespace-normalized → whitespace + diacritic-folded
    (fold chỉ "khi cần": pass trước đó đã fail). Offsets for a folded match
    may exclude a trailing combining mark in decomposed text — offsets are
    informational (client re-locates by phrase).
    """
    phrase = phrase.strip()
    if not phrase:
        return None
    i = page_text.find(phrase)
    if i >= 0:
        return i, i + len(phrase)
    for fold in (False, True):
        hay, hpos = _norm_map(page_text, fold)
        needle, _ = _norm_map(phrase, fold)
        if not needle:
            continue
        j = hay.find(needle)
        if j >= 0:
            return hpos[j], hpos[j + len(needle) - 1] + 1
    return None

def _page_text(page: dict) -> str:
    return "\n".join(r.get("text") or "" for r in page.get("regions", []))

def _parse(content: str) -> list[dict]:
    """LLM content → list of item dicts (bad shape → ProofreadError)."""
    if not isinstance(content, str):
        raise ProofreadError("phản hồi thiếu content (null)")
    try:
        data = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise ProofreadError(f"phản hồi không phải JSON: {exc}") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ProofreadError('phản hồi thiếu khóa "items"')
    return [it for it in items if isinstance(it, dict)]

async def _call_llm(page_text: str, hint: str) -> list[dict]:
    """One chat/completions POST (temperature 0, json_object, Bearer nếu có)."""
    payload: dict = {
        "model": settings.llm_model,
        "messages": [
            {"role": "user", "content": PROMPT.format(hint=hint, text=page_text)}
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
    async with AsyncClient(timeout=settings.llm_timeout) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProofreadError(f"LLM không phản hồi: {exc}") from exc
    if resp.status_code >= 400:
        raise ProofreadError(f"LLM HTTP {resp.status_code}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProofreadError(f"phản hồi thiếu content: {exc}") from exc
    return _parse(content)

async def run_proofread(session: AsyncSession, job: Job) -> int:
    """job.result pages → LLM → OcrSuggestion rows; returns count.

    LLM lỗi ở bất kỳ trang nào → WARNING + trả 0, không ghi gì (giữ gợi
    ý cũ). Exception khác (DB) lan lên caller — hook/route log riêng.
    """
    pages = (job.result or {}).get("pages") or []
    if not pages:
        return 0
    started = time.perf_counter()
    rows: list[OcrSuggestion] = []
    for index, page in enumerate(pages):
        text = _page_text(page)
        if not text.strip():
            continue
        hint = "\n".join(text.splitlines()[:3])  # context = 3 dòng đầu
        try:
            items = await _call_llm(text, hint)
        except ProofreadError as exc:
            logger.warning("proofread: LLM failed job=%s page=%d: %s", job.id, index, exc)
            return 0
        seen: set[tuple[str, str]] = set()
        for item in items:
            phrase = (item.get("phrase") or "").strip()
            suggestion = (item.get("suggestion") or "").strip()
            if not phrase or not suggestion:
                continue
            key = (phrase, suggestion)
            if key in seen:
                continue
            seen.add(key)
            hit = locate(text, phrase)
            if hit is None:
                continue  # fuzzy chặn phrase không tồn tại (LLM ảo giác)
            rows.append(
                OcrSuggestion(
                    job_id=job.id,
                    page_index=index,
                    start=hit[0],
                    end=hit[1],
                    original=phrase,
                    suggestion=suggestion,
                    reason=(item.get("reason") or "").strip(),
                )
            )
    # chạy lại = kết quả mới: drop cũ (mọi status) trước khi ghi
    await session.execute(delete(OcrSuggestion).where(OcrSuggestion.job_id == job.id))
    session.add_all(rows)
    await session.commit()
    logger.info(
        "proofread: job=%s pages=%d suggestions=%d elapsed=%.1fs",
        job.id, len(pages), len(rows), round(time.perf_counter() - started, 1),
    )
    return len(rows)
