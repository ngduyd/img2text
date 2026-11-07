"""Phase 1 Task 3 (plan 2026-10-10): incremental layout sync — 0 LLM.

raw text edited → patch artifacts in place: md-layout = plain-text replace;
docx.html = replace inside HTML TEXT NODES only (tags/attributes untouched).
Phrase not found in an artifact → that kind is NOT touched (atomic
per-layout; caller flags needs_render for it).
"""

from difflib import SequenceMatcher
from html import escape
from html.parser import HTMLParser
import logging

from app.services.layout_spec import reading_order_region_ids
from app.services.storage import StorageDriver

logger = logging.getLogger(__name__)

MD_LAYOUT_KEY = "exports/{job_id}/md-layout"
DOCX_HTML_KEY = "exports/{job_id}/docx.html"
# LLM render artifact (auto-gen/POST export fmt=docx-layout) — docx.html
# (user edit) supersedes it; history falls back to this when html chưa có.
DOCX_LAYOUT_KEY = "exports/{job_id}/docx-layout"


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

def _bbox_height(region: dict) -> float:
    """Chiều cao bbox (y1-y0); 0 khi thiếu/hỏng → caller fallback số dòng."""
    bbox = region.get("bbox")
    if not bbox or len(bbox) < 4:
        return 0.0
    try:
        return max(0.0, float(bbox[3]) - float(bbox[1]))
    except (TypeError, ValueError):
        return 0.0


def _region_index(result: dict) -> dict[str, tuple[int, int]]:
    """region id → (page_idx, region_idx)."""
    index: dict[str, tuple[int, int]] = {}
    for pi, page in enumerate(result.get("pages") or []):
        for ri, region in enumerate(page.get("regions") or []):
            index[str(region.get("id"))] = (pi, ri)
    return index


def text_from_regions(result: dict) -> str:
    """Text gốc theo THỨ TỰ ĐỌC (cột → y → x): regions join "\\n", pages "\\n\\n".

    Cùng thứ tự với layout render → sửa dòng nào thấy đúng chỗ đó. Region rỗng
    (ảnh) vẫn chiếm 1 dòng trống để text và layout khớp nhau.
    """
    index = _region_index(result)
    pages_text: list[str] = []
    pages = result.get("pages") or []
    for ids in reading_order_region_ids(result):
        lines = []
        for rid in ids:
            pi, ri = index[rid]
            lines.append(pages[pi]["regions"][ri].get("text") or "")
        pages_text.append("\n".join(lines))
    return "\n\n".join(pages_text)


def _find_run(lines: list[str], run: list[str], start: int) -> int | None:
    """Vị trí `run` xuất hiện LIÊN TIẾP trong lines, tìm từ `start`."""
    n, k = len(lines), len(run)
    for pos in range(start, n - k + 1):
        if lines[pos:pos + k] == run:
            return pos
    return None


def apply_text_to_regions(result: dict, new_text: str) -> bool:
    """Text phẳng user sửa (Overview) → regions[].text, neo theo bbox.

    Layout render (`build_page_specs` → md/docx) đọc regions, không đọc
    `extraction_text` → phải đẩy text mới ngược vào regions (bug job #84:
    sửa text xong layout in nguyên bản cũ).

    Neo 2 lớp: (1) mỗi region được tìm thấy trong text cũ theo NỘI DUNG (chạy
    liên tiếp, không phụ thuộc thứ tự lưu — row-major cũ hay column-major mới
    đều khớp); (2) phần bị viết lại chia cho các region trong span theo CHIỀU
    CAO bbox, dòng mới không có chủ → region TRƯỚC (chữ nằm ngay sau đoạn trên,
    nên không bị đẩy qua ảnh). Trả False khi không có region nào.
    ponytail: đủ cho sửa tay 1 người; upgrade = neo theo toạ độ từng dòng khi
    cần dựng lại layout từ text không còn giống bản OCR.
    """
    pages = result.get("pages") or []
    index = _region_index(result)
    if not index:
        return False
    old_text = result.get("extraction_text") or text_from_regions(result)
    old_lines = old_text.split("\n")
    owners: list[tuple[int, int] | None] = [None] * len(old_lines)
    cursor = 0
    for ids in reading_order_region_ids(result):
        for rid in ids:
            key = index[rid]
            text = pages[key[0]]["regions"][key[1]].get("text") or ""
            if not text:
                continue  # region ảnh/rỗng: không nhận chữ
            run = text.split("\n")
            pos = _find_run(old_lines, run, cursor)
            if pos is None:
                # text cũ có thể lưu theo thứ tự khác (row-major đời trước) →
                # tìm lại từ đầu thay vì bỏ neo
                pos = _find_run(old_lines, run, 0)
            if pos is None:
                continue  # đã bị sửa tay từ trước → để diff xử lý
            for k in range(len(run)):
                owners[pos + k] = key
            cursor = max(cursor, pos + len(run))
    if not any(owner is not None for owner in owners):
        return False  # không neo được gì → KHÔNG xoá text các region

    def target(i: int) -> tuple[int, int] | None:
        j = i
        while j < len(owners) and owners[j] is None:
            j += 1
        if j < len(owners):
            return owners[j]
        j = i - 1
        while j >= 0 and owners[j] is None:
            j -= 1
        return owners[j] if j >= 0 else None

    def owner_at(i: int) -> tuple[int, int] | None:
        return owners[i] if 0 <= i < len(owners) else None

    def prev_owner(i: int) -> tuple[int, int] | None:
        j = i
        while j >= 0 and owners[j] is None:
            j -= 1
        return owners[j] if j >= 0 else None

    assigned: dict[tuple[int, int], list[str]] = {}
    new_lines = new_text.split("\n")
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                owner = owners[i1 + k]
                if owner is not None:
                    assigned.setdefault(owner, []).append(old_lines[i1 + k])
            continue
        if tag == "delete":
            continue
        # insert = gõ thêm dòng NGAY SAU dòng cũ → thuộc region của dòng trước
        # (insert ở đầu → region đầu). replace = chia tỉ lệ theo số dòng cũ của
        # từng region trong span: user viết lại cả đoạn qua nhiều region thì
        # structure (và anchor ảnh cạnh đó) vẫn giữ được hình dạng.
        if tag == "insert":
            owner = owner_at(i1 - 1) or target(i1)
            if owner is not None:
                assigned.setdefault(owner, []).extend(new_lines[j1:j2])
            continue
        # Span bắt đầu ở dòng KHÔNG có chủ (dòng trống của vùng ảnh): chữ mới
        # nằm ngay dưới đoạn TRÊN ảnh → neo vào region trước, đừng đẩy xuống
        # region dưới ảnh.
        head = prev_owner(i1 - 1) if owner_at(i1) is None else None
        if head is not None:
            assigned.setdefault(head, []).extend(new_lines[j1:j2])
            continue
        spans: dict[tuple[int, int], int] = {}
        span_order: list[tuple[int, int]] = []
        for line_idx in range(i1, i2):
            filled = owners[line_idx]
            if filled is None:
                continue
            if filled not in spans:
                spans[filled] = 0
                span_order.append(filled)
            spans[filled] += 1
        chunk = new_lines[j1:j2]
        if not span_order:
            continue
        if len(span_order) == 1:
            assigned.setdefault(span_order[0], []).extend(chunk)
            continue
        # Trọng số = CHIỀU CAO bbox (neo vật lý: đoạn chữ chiếm bao nhiêu
        # khoảng giấy thì nhận bấy nhiêu dòng) — bbox thiếu/hỏng → số dòng cũ.
        weights = {
            owner: _bbox_height(pages[owner[0]]["regions"][owner[1]]) or spans[owner]
            for owner in span_order
        }
        total = sum(weights.values())
        idx = 0
        for pos, owner in enumerate(span_order):
            remaining = len(chunk) - idx
            if pos == len(span_order) - 1:
                take = remaining
            elif total > 0:
                take = round(len(chunk) * weights[owner] / total)
            else:
                take = len(chunk) // len(span_order)
            take = max(0, min(take, remaining))
            assigned.setdefault(owner, []).extend(chunk[idx:idx + take])
            idx += take
    for pi, page in enumerate(pages):
        for ri, region in enumerate(page.get("regions") or []):
            region["text"] = "\n".join(assigned.get((pi, ri), []))
    return True
