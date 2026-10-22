"""Exports router: content edit, export generation (md/html/docx/pdf), download, crops.

Sections: render helpers (pandoc/bleach/weasyprint, R27 sanitized failures,
R34 data-URI crop embedding) → content edit (PATCH /content, cache
invalidation) → export + download → region crops (R26: image jobs only).
Crops materialized into ALL md-family exports per Plan D Task 4.
"""

import asyncio
import base64
import io
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import bleach
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.convert import PANDOC_BIN, REFERENCE_DOCX
from app.core.db import get_session
from app.core.deps import get_current_user
from app.core.models import Job, User
from app.core.schemas import IMAGE_MARKER
from app.routers.jobs import _job_or_403, _text_bytes, bump_text_after_edit
from app.services.render_docx import build_docx
from app.services.render_html_spec import render_html_spec
from app.services.render_md import build_md, embed_crop_keys, embed_crop_urls
from app.services.doc_versions import save_version, snapshot_current_layout
from app.services.html_to_docx import html_to_docx, CROP_SRC_RE
from app.services.storage import StorageDriver, get_storage

logger = logging.getLogger(__name__)

# #14 (spec 2026-10-15): Noto Sans CJK ĐẦU stack — CJK glyph + dấu tiếng
# Việt (Dockerfile: fonts-noto-cjk); DejaVu Sans fallback quen thuộc
# (fonts-dejavu) cho env thiếu Noto. _render_pdf là đường PDF DUY NHẤT
# (render_md không render PDF) — test: tests/test_export_pdf_font.py.
# user stylesheet thắng CSS mặc định của pandoc.
PDF_FONT_CSS = "body { font-family: 'Noto Sans CJK', 'DejaVu Sans', serif; }"

# #10: single-range CHỈ bytes=start-end (cả hai đầu); suffix/multi/open-end
# → 416 (spec: supporting single-range only)
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d+)")

def _range_416(size: int) -> JSONResponse:
    """416 + Content-Range: bytes */size (RFC 9110 §14.4) — caller lookup
    size TRƯỚC (QA-2: kể cả Range rác cũng mang được size)."""
    return JSONResponse(
        status_code=416,
        content={"code": "invalid_range"},
        headers={"Content-Range": f"bytes */{size}"},
    )

EXPORT_PRESIGN_EXPIRES_SECONDS = 86400
# GET download Content-Type per fmt (Task 5 brief, verbatim)
EXPORT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Plan D2: same OOXML container, LLM layout plan instead of pandoc
    "docx-layout": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    # Plan D5: LLM md-layout is still plain markdown text
    "md-layout": "text/markdown; charset=utf-8",
    # Plan M3: user-edited word HTML artifact (iframe srcDoc source)
    "docx.html": "text/html; charset=utf-8",
}
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
CROP_MAX_WIDTH = 800
CROP_JPEG_QUALITY = 70
PANDOC_TIMEOUT_SECONDS = 55
# Exact marker emitted by worker/pipeline.py — shared IMAGE_MARKER (app.core.schemas)
# bleach allowlist covering pandoc html output (Task 4 brief, verbatim)
_HTML_TAGS = [
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "blockquote", "pre",
    "code", "em", "strong", "a", "img", "hr", "br", "div", "span",
]
_HTML_ATTRS = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

router = APIRouter(tags=["exports"])

# --- Render helpers: sanitization, crops, pandoc, pdf ---

def sanitize_pandoc_html(html: str) -> str:
    """bleach-clean pandoc html to a body fragment (script never executable).

    pandoc --standalone wrapper (html/head/meta/style) is not in the
    allowlist → extract body first so CSS/title text never leaks as visible
    junk; strip=True drops disallowed tags (script tag gone, text inert).
    """
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL)
    return bleach.clean(
        body.group(1) if body else html,
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRS,
        strip=True,
    )

def _embed_crops_as_data_uris(html: str, tempdir: Path) -> str:
    """Rewrite pandoc <img src="crops/X.jpg"> to data URIs (html/pdf path).

    Presign URLs don't carry the tempdir, so relative crop refs 404 when
    the exported html is opened; data URIs are self-contained. Applied
    AFTER bleach (R34-bounded): data: URLs stay out of the global allowlist
    because data:href is click-XSS on the R2 origin.
    """
    def _repl(m: re.Match) -> str:
        crop = tempdir / m.group(1)
        try:
            b64 = base64.b64encode(crop.read_bytes()).decode("ascii")
        except OSError:
            return m.group(0)  # crop missing → keep ref (no data loss)
        mime = "png" if m.group(1).endswith(".png") else "jpeg"
        return f'src="data:image/{mime};base64,{b64}"'

    # jpg = on-demand crop (fallback); png = batch crop kernel (chính)
    return re.sub(r'src="(crops/[^\"]+\.(?:jpg|png))"', _repl, html)

def _run_pandoc(cmd: list[str], fmt: str, job_id: int, cwd: Path) -> None:
    """Run pandoc; any failure → sanitized 500 (never raw subprocess error)."""
    try:
        # cwd=tempdir: markdown image paths (crops/{rid}.png|jpg) resolve here
        proc = subprocess.run(
            cmd, capture_output=True, timeout=PANDOC_TIMEOUT_SECONDS, cwd=str(cwd)
        )
    except FileNotFoundError:
        # R27: pandoc binary missing must sanitize, not raw-500
        logger.warning("pandoc missing fmt=%s job=%s", fmt, job_id)
        raise HTTPException(status_code=500, detail="Xuất file thất bại.")
    except subprocess.TimeoutExpired:
        logger.warning("pandoc timed out fmt=%s job=%s", fmt, job_id)
        raise HTTPException(status_code=500, detail="Xuất file thất bại.")
    if proc.returncode != 0:
        # sanitized: stdout/stderr to log only, never the response body
        logger.warning(
            "pandoc failed fmt=%s job=%s rc=%s stderr=%s",
            fmt,
            job_id,
            proc.returncode,
            proc.stderr[:500],
        )
        raise HTTPException(status_code=500, detail="Xuất file thất bại.")

def current_markdown(result: dict) -> str:
    """Latest markdown: user-edited wins over worker output (later tasks reuse)."""
    return result.get("edited_markdown") or result["markdown"]

def find_region(result: dict, rid: str) -> dict | None:
    """Region by id across all pages (later tasks reuse)."""
    for page in result.get("pages", []):
        for region in page.get("regions", []):
            if region["id"] == rid:
                return region
    return None

async def get_or_make_crop(
    job_id: int, rid: str, job: Job, result: dict, storage: StorageDriver
) -> str:
    """Lazy crop cache: crops/{job_id}/{rid}.jpg; returns storage key.

    Missing region/bbox None → KeyError (route maps to 404). Original
    missing in R2 → KeyError (route maps to 404 with spec §4 message).
    """
    key = f"crops/{job_id}/{rid}.jpg"
    region = find_region(result, rid)
    if region is None:
        raise KeyError(rid)
    bbox = region.get("bbox")
    if bbox is None:
        raise KeyError(rid)
    if await storage.exists(key):  # cache hit: presign only
        return key
    x1, y1, x2, y2 = bbox
    try:
        original = await storage.get(job.storage_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="File gốc không tồn tại.")
    img = Image.open(io.BytesIO(original))
    # no exif_transpose: crop must match VLM pixel frame (worker sees raw pixels)
    img = img.convert("RGB")  # RGBA/P-mode/WEBP originals cannot save as JPEG
    crop = img.crop((x1, y1, x2, y2))
    if crop.width > CROP_MAX_WIDTH:
        crop = crop.resize(
            (CROP_MAX_WIDTH, crop.height * CROP_MAX_WIDTH // crop.width)
        )
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=CROP_JPEG_QUALITY)
    await storage.put(key, buf.getvalue())
    return key

async def _materialize_crops(
    job_id: int, markdown: str, job: Job, storage: StorageDriver, tempdir: Path
) -> str:
    """Marker→image rewrite: materialize crops into tempdir/crops/{rid}.{png,jpg}.

    Batch crop kernel `exports/{job_id}/crops/{rid}.png` thắng (server chỉ
    LƯỮ + DÙNG); thiếu → on-demand `crops/{job_id}/{rid}.jpg` (fallback).

    Region verdict image_unextractable WITH bbox → crop cached/generated,
    marker `**[Hình ảnh chưa trích xuất: vùng {rid}]**` replaced by
    `![vùng {rid}](crops/{rid}.png)` (batch) hoặc `(crops/{rid}.jpg)`
    (fallback). bbox-less/missing regions keep the
    marker text (Plan D Global Constraints). Returns rewritten markdown.
    """
    result = dict(job.result or {})
    for page in result.get("pages", []):
        for region in page.get("regions", []):
            if region.get("verdict") != "image_unextractable":
                continue
            if region.get("bbox") is None:
                continue
            rid = region["id"]
            marker = IMAGE_MARKER.format(region_id=rid)
            if marker not in markdown:
                continue  # no marker → no rewrite → no crop needed
            # batch-first (Lane K): crop kernel đã ingest → DÙNG, server
            # không cắt lại; on-demand jpg chỉ fallback khi batch thiếu.
            fname = f"{rid}.jpg"
            try:
                crop_bytes = await storage.get(
                    f"exports/{job_id}/crops/{rid}.png"
                )
                fname = f"{rid}.png"
            except KeyError:
                try:
                    key = await get_or_make_crop(job_id, rid, job, result, storage)
                    crop_bytes = await storage.get(key)
                except KeyError:
                    # R27: only KeyError swallowed; HTTPException (missing
                    # original) and other R2 failures must propagate
                    continue
            crop_dir = tempdir / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            (crop_dir / fname).write_bytes(crop_bytes)
            # ceiling: .md exports need sibling crops/ dir (documented)
            markdown = markdown.replace(marker, f"![vùng {rid}](crops/{fname})")
    return markdown

async def _pandoc_export(
    fmt: str, job_id: int, markdown: str, job: Job, storage: StorageDriver
) -> bytes:
    """pandoc markdown→fmt via tempdir (crops materialized first); 500 on failure.

    html output is bleach-sanitized; docx goes through pandoc's own parser.
    """
    with tempfile.TemporaryDirectory() as td:
        tempdir = Path(td)
        in_md = tempdir / "in.md"
        in_md.write_text(
            await _materialize_crops(job_id, markdown, job, storage, tempdir),
            encoding="utf-8",
        )
        out = tempdir / f"out.{fmt}"
        cmd = [PANDOC_BIN, "-f", "markdown", "-t", fmt]
        if fmt == "html":
            cmd.append("--standalone")
        else:  # docx: reference styles from committed deploy/reference.docx
            cmd += ["--reference-doc", REFERENCE_DOCX]
        cmd += ["-o", str(out), str(in_md)]
        _run_pandoc(cmd, fmt, job_id, tempdir)
        data = out.read_bytes()
        if fmt == "html":  # sanitize AFTER pandoc (markdown itself cannot carry script)
            clean = sanitize_pandoc_html(data.decode("utf-8"))
            # post-bleach: relative crop refs → data URIs (html opened from
            # presign URL can't resolve crops/ siblings; R34, not global)
            clean = _embed_crops_as_data_uris(clean, tempdir)
            data = clean.encode("utf-8")
        return data

async def _pdf_export(
    job_id: int, markdown: str, job: Job, storage: StorageDriver
) -> bytes:
    """pdf: materialized markdown → pandoc html → bleach → weasyprint bytes.

    weasyprint import+render runs in a thread (CPU-bound, avoid blocking loop).
    """
    with tempfile.TemporaryDirectory() as td:
        tempdir = Path(td)
        in_md = tempdir / "in.md"
        in_md.write_text(
            await _materialize_crops(job_id, markdown, job, storage, tempdir),
            encoding="utf-8",
        )
        out = tempdir / "out.html"
        cmd = [
            PANDOC_BIN, "-f", "markdown", "-t", "html", "--standalone",
            "-o", str(out), str(in_md),
        ]
        _run_pandoc(cmd, "html", job_id, tempdir)
        clean_html = sanitize_pandoc_html(out.read_text(encoding="utf-8"))
        # same clean html as html export: crop refs → data URIs (R34)
        clean_html = _embed_crops_as_data_uris(clean_html, tempdir)
        # heavy weasyprint import + pdf render off the event loop
        return await asyncio.to_thread(_render_pdf, clean_html, str(tempdir))

def _render_pdf(html: str, base_url: str) -> bytes:
    """bleach-cleaned html → pdf via weasyprint (import inside: heavy, in thread)."""
    from weasyprint import CSS, HTML  # deferred import: CPU-heavy, runs in to_thread

    font_css = CSS(string=PDF_FONT_CSS)
    return HTML(string=html, base_url=base_url).write_pdf(
        stylesheets=[font_css]
    )

# --- Content edit: PATCH /api/jobs/{id}/content ---

class ContentBody(BaseModel):
    markdown: str

    @field_validator("markdown")
    @classmethod
    def _nonempty_2mb(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("markdown không được để trống.")
        if len(v.encode()) > MAX_MARKDOWN_BYTES:
            raise ValueError("markdown vượt quá 2MB.")
        return v

class ExportBody(BaseModel):
    fmt: Literal["md", "html", "docx", "pdf", "docx-layout", "md-layout"]

class MdLayoutContentBody(BaseModel):
    # length/emptiness checked in the route → exact 422 detail
    markdown: str

MAX_MD_LAYOUT_CHARS = 500_000

@router.put("/api/jobs/{id}/export/md-layout/content", status_code=204)
async def put_md_layout_content(
    id: int,
    body: MdLayoutContentBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Plan M: lưu bản md-layout đã sửa (upsert exports/{id}/md-layout).

    Separate from PATCH /content (job.content): content = raw OCR/edit,
    md-layout = LLM layout + user's source edits (spec binding).
    """
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    if not body.markdown.strip():
        raise HTTPException(status_code=422, detail="Nội dung trống.")
    if len(body.markdown) > MAX_MD_LAYOUT_CHARS:
        raise HTTPException(status_code=422, detail="Nội dung quá dài.")
    key = f"exports/{id}/md-layout"
    # S3Driver.put dedupes existing keys → delete first for upsert
    await storage.delete_prefix(key)
    await storage.put(key, body.markdown.encode("utf-8"))
    # Phase 1 T6 (Task 6): direct layout edit → mark detached + snapshot
    await save_version(
        storage, id, "md-layout", body.markdown.encode("utf-8"),
        job.text_version, detached=True, session=session,
    )
    return Response(status_code=204)

class DocxHtmlBody(BaseModel):
    # length checked in the route → exact 422 detail
    html: str

MAX_DOCX_HTML_CHARS = 1_000_000  # Plan M3: ≤1MB else 422 "Nội dung quá dài."

@router.put("/api/jobs/{id}/export/docx-layout/html", status_code=204)
async def put_docx_layout_html(
    id: int,
    body: DocxHtmlBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Plan M3: lưu HTML word đã sửa (iframe serialize) → exports/{id}/docx.html.

    Owner-or-admin, done-only 409, ≤1MB else 422 "Nội dung quá dài.".
    Derived exports/{id}/docx must not outlive the html edit → prefix delete
    BEFORE put (S3Driver.put dedupes). NOTE: the prefix also matches
    docx-layout + old docx.html — all superseded by the new html (user edit
    beats LLM render; mammoth fallback no longer needed).
    """
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    if len(body.html) > MAX_DOCX_HTML_CHARS:
        raise HTTPException(status_code=422, detail="Nội dung quá dài.")
    await storage.delete_prefix(f"exports/{id}/docx")
    await storage.put(f"exports/{id}/docx.html", body.html.encode("utf-8"))
    # Phase 1 T6 (Task 6): direct layout edit → mark detached + snapshot
    await save_version(
        storage, id, "docx-layout", body.html.encode("utf-8"),
        job.text_version, detached=True, session=session,
    )
    return Response(status_code=204)

@router.patch("/api/jobs/{id}/content")
async def patch_content(
    id: int,
    body: ContentBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    # P1-3: the wipe destroys layout artifacts → snapshot them into version
    # history first (user edit of content → detached snapshots).
    await snapshot_current_layout(
        storage, session, id, "md-layout", job.text_version, detached=True
    )
    await snapshot_current_layout(
        storage, session, id, "docx-layout", job.text_version, detached=True
    )
    result = dict(job.result or {})  # JSONB merge: copy, set, reassign
    # P1-R1: capture text gốc TRƯỚC khi ghi edited_markdown → seed v1 giữ bản gốc
    pre_bytes = _text_bytes(result)
    result["edited_markdown"] = body.markdown
    job.result = result
    # P1-2/R3: bump với bytes = nội dung vừa lưu (snapshot phản ánh edit)
    await bump_text_after_edit(
        session, storage, job,
        data=body.markdown.encode("utf-8"), seed_bytes=pre_bytes,
    )
    # cache invalidation: exported md must reflect the edit
    await storage.delete_prefix(f"exports/{id}/")
    # P2-3: response mang text_version MỚI — client/API thô biết tv đã bump
    return {"text_version": job.text_version}

# --- Export generation + download: POST /export, GET /export/{fmt}/download ---

async def _llm_docx_export(
    job_id: int, job: Job, storage: StorageDriver | None = None,
) -> bytes:
    """Layout-spec rewrite: result → docx bytes (0 LLM call, deterministic).

    Missing result → 409 "Chưa có kết quả OCR.".
    Plan M: jobs.layout_style applied over the spec render (user wins).
    """
    result = dict(job.result or {})
    if not result.get("pages"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    crop_loader = None
    if storage is not None:
        async def _on_demand_crop(rid: str) -> bytes | None:
            try:  # batch crop kernel thắng (server chỉ lưu + dùng)
                return await storage.get(f"exports/{job_id}/crops/{rid}.png")
            except KeyError:
                pass
            try:
                key = await get_or_make_crop(job_id, rid, job, result, storage)
                return await storage.get(key)
            except KeyError:
                return None

        crop_loader = _on_demand_crop
    return await build_docx(
        result, style_overrides=_job_layout_style(job), crop_loader=crop_loader
    )

def _job_layout_style(job: Job) -> dict | None:
    """jobs.layout_style JSON → dict; broken JSON → None + warning."""
    if not job.layout_style:
        return None
    try:
        style = json.loads(job.layout_style)
    except (ValueError, TypeError) as exc:
        logger.warning("job %s layout_style JSON hỏng: %s", job.id, exc)
        return None
    return style if isinstance(style, dict) else None

async def _llm_md_export(
    job_id: int, job: Job, storage: StorageDriver | None = None,
) -> bytes:
    """Layout-spec rewrite: result → markdown bytes (0 LLM call, deterministic).

    Missing result → 409 "Chưa có kết quả OCR."
    storage (WS-PIPE): figure marker → presigned crop URL 24h nếu crop
    artifact đã ingest; thiếu → on-demand crop → data-URI; loader fail →
    giữ marker.
    """
    result = dict(job.result or {})
    if not result.get("pages"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    md = await build_md(result)
    if storage is not None:
        # render: relative crops/{f} key (presigned 24h hết hạn → chết);
        # crop artifact thiếu → on-demand crop (route /regions/{rid}/crop
        # logic) → data-URI self-contained (wave-4 #9)
        async def _on_demand_crop(rid: str) -> bytes:
            key = await get_or_make_crop(job_id, rid, job, result, storage)
            return await storage.get(key)

        md = await embed_crop_keys(
            md, job_id, storage, crop_loader=_on_demand_crop
        )
    return md.encode("utf-8")

async def _docx_html_export(
    job_id: int, job: Job, storage: StorageDriver
) -> bytes | None:
    """Plan M3: exports/{id}/docx.html → python-docx walker; None if absent
    (caller falls back to the pandoc docx path).

    WS-PIPE: img src tham chiếu crop artifact → load bytes; batch miss →
    on-demand get_or_make_crop (S1a). Partial-fail: crop KeyError → img drop
    trong walker; HTTPException propagate (R27)."""
    key = f"exports/{job_id}/docx.html"
    if not await storage.exists(key):
        return None
    html = (await storage.get(key)).decode("utf-8")
    crops: dict[str, bytes] = {}
    for rid in {m.group(1) for m in CROP_SRC_RE.finditer(html)}:
        try:
            crops[rid] = await storage.get(f"exports/{job_id}/crops/{rid}.png")
        except KeyError:
            try:  # batch miss → on-demand (S1a), không drop img oan
                crop_key = await get_or_make_crop(
                    job_id, rid, job, job.result or {}, storage
                )
                crops[rid] = await storage.get(crop_key)
            except KeyError:
                logger.info("docx export: crop %s chưa ingest — img bị drop", rid)
    return html_to_docx(html, crops=crops)

async def auto_generate_output(job: Job, storage: StorageDriver) -> bool:
    """Generate BOTH md-layout and docx-layout eagerly after OCR.

    User request: both formats ready before viewing — no LLM wait at view
    time. Each format is independent: one failing logs a warning, the
    other still generates.
    Returns True iff ≥1 LAYOUT artifact (md-layout / docx-layout) was
    written — the spec 2026-10-09 completion rule the caller applies:
    at least one OK → done, both fail → failed + failed_step="rendering"
    (the plain-md fallback is a degraded artifact, not a layout success).
    Render là layout_spec (0 LLM call); GET /api/jobs/{id}/ir sinh
    on-demand (job.ir_json NULL → generate_ir lần đầu, sau đó cache DB).
    Reuses the export_job internals (NO HTTP round-trip); scheduled
    fire-and-forget by job_results AFTER the result commit.
    Phase 5: extract_only jobs return False immediately — no layout
    artifacts (covers retry_layout path; the auto-output task short-
    circuits on mode and marks the job done itself).
    """
    if job.mode == "extract_only":
        return False
    md_ok = False
    # md-layout (spec) — failure → warning + fallback plain md at exports/{id}/md
    try:
        data = await _llm_md_export(job.id, job, storage)
        # P1-3: overwrite must not wipe unsnapshotted artifact bytes
        await snapshot_current_layout(storage, None, job.id, "md-layout", job.text_version)
        # P0-A: S3Driver.put dedupes existing keys → delete first, else
        # retry-layout/auto-gen can never overwrite the stale artifact
        await storage.delete_prefix(f"exports/{job.id}/md-layout")
        await storage.put(f"exports/{job.id}/md-layout", data)
        md_ok = True
    except Exception as exc:  # HTTPException 409 hoặc lỗi render bất ngờ → fallback
        logger.warning(
            "md-layout auto-gen failed job=%s: %s — fallback plain md",
            job.id, getattr(exc, "detail", exc),
        )
        markdown = current_markdown(job.result or {})
        # same md branch as export_job: crops materialized before encode
        with tempfile.TemporaryDirectory() as td:
            markdown = await _materialize_crops(
                job.id, markdown, job, storage, Path(td)
            )
        await storage.put(f"exports/{job.id}/md", markdown.encode("utf-8"))
    # docx-layout (spec) — failure → warning (independent of md above)
    docx_ok = False
    try:
        data = await _llm_docx_export(job.id, job, storage)
        # P2-4: overwrite must not wipe unsnapshotted artifact bytes
        # (trước đây chỉ md-layout snapshot — docx-layout mất bản cũ)
        await snapshot_current_layout(
            storage, None, job.id, "docx-layout", job.text_version
        )
        # P0-A: same dedupe rule as md-layout — delete before put (exact key:
        # user-edited docx.html must survive an LLM re-render)
        await storage.delete_prefix(f"exports/{job.id}/docx-layout")
        await storage.put(f"exports/{job.id}/docx-layout", data)
        docx_ok = True
    except Exception as exc:  # độc lập với md ở trên; lỗi bất kỳ → chỉ warning
        logger.warning(
            "docx-layout auto-gen failed job=%s: %s", job.id,
            getattr(exc, "detail", exc),
        )
    return md_ok or docx_ok

@router.post("/api/jobs/{id}/export")
async def export_job(
    id: int,
    body: ExportBody,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    key = f"exports/{id}/{body.fmt}"
    if not await storage.exists(key):  # cache hit → presign only, no re-generate
        if body.fmt == "docx-layout":
            data = await _llm_docx_export(id, job, storage=storage)
        elif body.fmt == "md-layout":
            data = await _llm_md_export(id, job, storage=storage)
        elif body.fmt == "docx" and (
            data := await _docx_html_export(id, job, storage)
        ) is not None:
            pass  # Plan M3: user-edited docx.html wins over pandoc
        else:
            markdown = current_markdown(job.result or {})
            if body.fmt == "pdf":
                data = await _pdf_export(id, markdown, job, storage)
            elif body.fmt == "md":
                # Task 4: crops embedded in ALL md-family exports
                with tempfile.TemporaryDirectory() as td:
                    markdown = await _materialize_crops(
                        id, markdown, job, storage, Path(td)
                    )
                data = markdown.encode()
            else:  # html (bleach-sanitized) / docx via pandoc
                data = await _pandoc_export(body.fmt, id, markdown, job, storage)
        if body.fmt == "md-layout":
            # P1-3: keep previous artifact bytes in version history
            await snapshot_current_layout(storage, session, id, "md-layout", job.text_version)
        await storage.put(key, data)
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}

@router.get("/api/jobs/{id}/export/{fmt}/download")
async def download_export(
    id: int,
    fmt: Literal["md", "html", "docx", "pdf", "docx-layout", "md-layout",
                  "docx.html"],
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Same-origin download of a cached export (Task 5; client shows blob).

    fmt is a Literal path segment — no user path reaches storage keys.
    Cache miss → 404: client must POST /export first to generate.
    #10: Range header → 206 Partial Content (single bytes=start-end; suffix/
    multi/malformed/out-of-bounds → 416) — resume download không cần kéo
    lại toàn file."""
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    key = f"exports/{id}/{fmt}"
    rng = request.headers.get("range")
    if rng is None:
        try:
            data = await storage.get(key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Chưa xuất file.")
        if fmt == "md-layout":
            # serve-time: relative crops/{f} → presigned 24h FRESH (URL không hết hạn)
            md = await embed_crop_urls(data.decode("utf-8"), id, storage)
            data = md.encode("utf-8")
        # QA-3: advertise range support để client biết resume được
        return Response(
            content=data,
            media_type=EXPORT_CONTENT_TYPES[fmt],
            headers={"Accept-Ranges": "bytes"},
        )
    m = _RANGE_RE.fullmatch(rng)
    if m is None or int(m.group(2)) < int(m.group(1)):
        # QA-2: Range rác/malformed → vẫn 416 có Content-Range */size
        # (md-layout: size của representation lưu — header rác không đáng
        # 1 lần transform toàn file)
        try:
            size = await storage.size(key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Chưa xuất file.")
        return _range_416(size)
    start, end = int(m.group(1)), int(m.group(2))
    if fmt == "md-layout":
        # serve-time re-encode (crop URL embed) → range tính trên representation CUỐI
        try:
            full = await storage.get(key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Chưa xuất file.")
        md = await embed_crop_urls(full.decode("utf-8"), id, storage)
        final = md.encode("utf-8")
        if start >= len(final):
            return _range_416(len(final))
        chunk = final[start:end + 1]
        total = len(final)
    else:
        try:
            size = await storage.size(key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Chưa xuất file.")
        if start >= size:
            return _range_416(size)
        try:
            chunk = await storage.get_range(key, start, end)
        except ValueError:
            return _range_416(size)
        except KeyError:
            # QA-1: purge race — object mất giữa size() và get_range → 404
            # (md-layout nhánh trên đã catch; nhánh này giờ giống)
            raise HTTPException(status_code=404, detail="Chưa xuất file.")
        total = size
    return Response(
        content=chunk,
        status_code=206,
        media_type=EXPORT_CONTENT_TYPES[fmt],
        headers={
            "Content-Range": f"bytes {start}-{start + len(chunk) - 1}/{total}"
        },
    )

@router.get("/api/jobs/{id}/preview/layout.html", response_class=HTMLResponse)
async def preview_layout_html(
    id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> HTMLResponse:
    """Preview Word dựng từ layout_spec (KHÔNG convert docx).

    Trước: web convert docx→HTML bằng mammoth → mất tab stop, canh lề, OMML
    (bản xem trước khác bản tải về). Đây là cùng nguồn với docx-layout nên
    preview khớp file: công thức = MathML, header 2 bên = 2 đầu, justify giữ.
    Ảnh: crop presigned (fallback marker khi thiếu crop).
    """
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    result = job.result or {}
    crop_urls: dict[str, str] = {}
    for page in result.get("pages", []):
        for region in page.get("regions", []):
            if not (region.get("placeholder")
                    or region.get("verdict") == "image_unextractable"):
                continue
            rid = str(region.get("id"))
            try:
                key = await get_or_make_crop(id, rid, job, result, storage)
                crop_urls[rid] = await storage.presign_get(
                    key, EXPORT_PRESIGN_EXPIRES_SECONDS
                )
            except KeyError:
                logger.info("preview: crop %s thiếu → marker", rid)
    return HTMLResponse(render_html_spec(result, crop_urls=crop_urls))

# --- Region crops: GET /api/jobs/{id}/regions/{rid}/crop ---

@router.get("/api/jobs/{id}/regions/{rid}/crop")
async def region_crop(
    id: int,
    rid: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> dict:
    job = await _job_or_403(session, id, user)
    if job.file_type != "image":
        # ruling R26: PDF jobs have no PIL-decodable original
        raise HTTPException(status_code=404, detail="Crop chỉ hỗ trợ file ảnh.")
    result = dict(job.result or {})
    try:
        key = await get_or_make_crop(id, rid, job, result, storage)
    except KeyError:
        raise HTTPException(status_code=404)
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}
