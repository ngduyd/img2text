"""Exports router: content edit, export generation (md/html/docx/pdf), download, crops.

Sections: render helpers (pandoc/bleach/weasyprint, R27 sanitized failures,
R34 data-URI crop embedding) → content edit (PATCH /content, cache
invalidation) → export + download → region crops (R26: image jobs only).
Crops materialized into ALL md-family exports per Plan D Task 4.
"""

import asyncio
import base64
import io
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import bleach
from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.convert import PANDOC_BIN, REFERENCE_DOCX
from app.core.db import get_session
from app.core.deps import get_current_user
from app.core.models import Job, User
from app.routers.jobs import _job_or_403
from app.services.llm_docx import LLMLayoutError, build_layout_docx
from app.services.storage import StorageDriver, get_storage

logger = logging.getLogger(__name__)

EXPORT_PRESIGN_EXPIRES_SECONDS = 86400
# GET download Content-Type per fmt (Task 5 brief, verbatim)
EXPORT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Plan D2: same OOXML container, LLM layout plan instead of pandoc
    "docx-layout": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
CROP_MAX_WIDTH = 800
CROP_JPEG_QUALITY = 70
PANDOC_TIMEOUT_SECONDS = 55
# Exact marker emitted by worker/pipeline.py for unextractable image regions.
_MARKER = "**[Hình ảnh chưa trích xuất: vùng {rid}]**"
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
        return f'src="data:image/jpeg;base64,{b64}"'

    return re.sub(r'src="(crops/[^\"]+\.jpg)"', _repl, html)

def _run_pandoc(cmd: list[str], fmt: str, job_id: int, cwd: Path) -> None:
    """Run pandoc; any failure → sanitized 500 (never raw subprocess error)."""
    try:
        # cwd=tempdir: markdown image paths (crops/{rid}.jpg) resolve here
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
    """Marker→image rewrite: materialize crops into tempdir/crops/{rid}.jpg.

    Region verdict image_unextractable WITH bbox → crop cached/generated,
    marker `**[Hình ảnh chưa trích xuất: vùng {rid}]**` replaced by
    `![vùng {rid}](crops/{rid}.jpg)`. bbox-less/missing regions keep the
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
            marker = _MARKER.format(rid=rid)
            if marker not in markdown:
                continue  # no marker → no rewrite → no crop needed
            try:
                key = await get_or_make_crop(job_id, rid, job, result, storage)
                crop_bytes = await storage.get(key)
            except KeyError:
                # R27: only KeyError swallowed; HTTPException (missing
                # original) and other R2 failures must propagate
                continue
            crop_dir = tempdir / "crops"
            crop_dir.mkdir(parents=True, exist_ok=True)
            (crop_dir / f"{rid}.jpg").write_bytes(crop_bytes)
            # ceiling: .md exports need sibling crops/ dir (documented)
            markdown = markdown.replace(marker, f"![vùng {rid}](crops/{rid}.jpg)")
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
    from weasyprint import HTML  # deferred import: CPU-heavy, runs in to_thread

    return HTML(string=html, base_url=base_url).write_pdf()

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
    fmt: Literal["md", "html", "docx", "pdf", "docx-layout"]

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
    result = dict(job.result or {})  # JSONB merge: copy, set, reassign
    result["edited_markdown"] = body.markdown
    job.result = result
    await session.commit()
    # cache invalidation: exported md must reflect the edit
    await storage.delete_prefix(f"exports/{id}/")
    return {}

# --- Export generation + download: POST /export, GET /export/{fmt}/download ---

async def _llm_docx_export(job_id: int, job: Job) -> bytes:
    """Plan D2: result → LLM layout plan → docx bytes (never caches errors).

    Missing result → 409 "Chưa có kết quả OCR."; LLM unreachable/timeout
    → 502 "Không kết nối LLM máy chủ." (raised before storage.put).
    """
    result = dict(job.result or {})
    if not result.get("pages"):
        raise HTTPException(status_code=409, detail="Chưa có kết quả OCR.")
    page_dims = [
        (page.get("width") or 0, page.get("height") or 0)
        for page in result["pages"]
    ]
    try:
        return await build_layout_docx(result, page_dims)
    except LLMLayoutError as exc:
        logger.warning("docx-layout LLM failure job=%s: %s", job_id, exc)
        raise HTTPException(
            status_code=502, detail="Không kết nối LLM máy chủ."
        ) from exc

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
            data = await _llm_docx_export(id, job)
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
        await storage.put(key, data)
    url = await storage.presign_get(key, EXPORT_PRESIGN_EXPIRES_SECONDS)
    return {"url": url}

@router.get("/api/jobs/{id}/export/{fmt}/download")
async def download_export(
    id: int,
    fmt: Literal["md", "html", "docx", "pdf", "docx-layout"],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageDriver = Depends(get_storage),
) -> Response:
    """Same-origin download of a cached export (Task 5; client shows blob).

    fmt is a Literal path segment — no user path reaches storage keys.
    Cache miss → 404: client must POST /export first to generate.
    """
    job = await _job_or_403(session, id, user)
    if job.status != "done":
        raise HTTPException(status_code=409, detail="job not done")
    try:
        data = await storage.get(f"exports/{id}/{fmt}")
    except KeyError:
        raise HTTPException(status_code=404, detail="Chưa xuất file.")
    return Response(content=data, media_type=EXPORT_CONTENT_TYPES[fmt])

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
