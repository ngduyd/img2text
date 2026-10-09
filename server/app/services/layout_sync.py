"""Phase 1 Task 3 (plan 2026-10-10): incremental layout sync — 0 LLM.

raw text edited → patch artifacts in place: md-layout = plain-text replace;
docx.html = replace inside HTML TEXT NODES only (tags/attributes untouched).
Phrase not found in an artifact → that kind is NOT touched (atomic
per-layout; caller flags needs_render for it).
"""

from html import escape
from html.parser import HTMLParser
import logging

from app.services.storage import StorageDriver

logger = logging.getLogger(__name__)

MD_LAYOUT_KEY = "exports/{job_id}/md-layout"
DOCX_HTML_KEY = "exports/{job_id}/docx.html"


def sync_md_layout(md_text: str, old: str, new: str, count: int = -1) -> str | None:
    """old→new plain replace; None = old not found (artifact untouched)."""
    if old not in md_text:
        return None
    return md_text.replace(old, new, count)


class _TextSpans(HTMLParser):
    """Text-node source spans (absolute offsets into the raw html).

    convert_charrefs=False keeps data chunks byte-accurate against the
    source (decoded entities would break the offset math).
    """

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.spans: list[tuple[int, int]] = []
        self._line_starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                self._line_starts.append(i + 1)

    def handle_data(self, data: str) -> None:
        line, col = self.getpos()
        start = self._line_starts[line - 1] + col
        self.spans.append((start, start + len(data)))


def sync_docx_html(html: str, old: str, new: str) -> str | None:
    """Replace old→new inside text nodes only (tags preserved); None = absent.

    Spans are located first, then replaced back-to-front so earlier offsets
    stay valid; a phrase spanning two text nodes is not found (never
    rewrites across tags — would corrupt the document).

    P1-2: `new` is html-escaped before insertion — user text can never
    inject markup into the DOM. Limitation: `old` is searched raw against
    source, so a phrase containing an entity (e.g. "&amp;") is never found.
    """
    safe_new = escape(new)
    parser = _TextSpans(html)
    parser.feed(html)
    parser.close()
    out = html
    replaced = 0
    for start, end in reversed(parser.spans):
        seg = html[start:end]
        n = seg.count(old)
        if n:
            out = out[:start] + seg.replace(old, safe_new) + out[end:]
            replaced += n
    return out if replaced else None


async def sync_job_layouts(
    storage: StorageDriver, job_id: int, old: str, new: str
) -> dict:
    """Patch BOTH editable layouts in storage; per-kind {synced: bool}.

    False = phrase absent OR artifact missing (caller → needs_render);
    synced artifact is persisted immediately (delete first — S3Driver.put
    dedupes existing keys). docx.html sync invalidates derived exports/
    {id}/docx* first (same supersede rule as PUT docx-layout/html).
    """
    md_ok = await _sync_one(
        storage, MD_LAYOUT_KEY.format(job_id=job_id), old, new, sync_md_layout,
    )
    docx_key = DOCX_HTML_KEY.format(job_id=job_id)
    docx_ok = await _sync_one(
        storage, docx_key, old, new, sync_docx_html, delete_prefix=f"exports/{job_id}/docx"
    )
    return {"md": md_ok, "docx": docx_ok}


async def _sync_one(
    storage: StorageDriver,
    key: str,
    old: str,
    new: str,
    syncer,
    delete_prefix: str | None = None,
) -> bool:
    """Per-layout failure isolation (P2): any error → False (needs_render),
    never aborts the sibling layout after text is already committed."""
    try:
        if not await storage.exists(key):
            return False
        text = (await storage.get(key)).decode("utf-8")
        updated = syncer(text, old, new)
        if updated is None:
            return False
        await storage.delete_prefix(delete_prefix or key)
        await storage.put(key, updated.encode("utf-8"))
        return True
    except Exception as exc:
        logger.warning("layout sync failed key=%s: %s", key, exc)
        return False
