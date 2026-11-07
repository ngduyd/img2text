"""Vòng VLM-preview cho layout Word: job → .docx → PDF → PNG (cạnh trang gốc).

Dùng cho dev: so `docx.png` (Word render qua LibreOffice) với `page.png`
(trang gốc rasterize bằng PyMuPDF) để biết Word có giữ được layout không.

    .venv/bin/python scripts/docx_layout_preview.py 84 [--out /tmp/docx-preview]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.models import Job  # noqa: E402
from app.routers.exports import get_or_make_crop  # noqa: E402
from app.services.render_docx import build_docx  # noqa: E402
from app.services.storage import build_storage  # noqa: E402

RENDER_IMAGE = "img2text-docx-render"


async def _load(job_id: int):
    async with SessionLocal() as session:
        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalars().first()
        if job is None:
            raise SystemExit(f"không thấy job {job_id}")
        return job


async def _make_docx(job, out: Path) -> Path:
    storage = build_storage()
    result = dict(job.result or {})

    async def crop_loader(rid: str) -> bytes | None:
        try:
            key = await get_or_make_crop(job.id, rid, job, result, storage)
            return await storage.get(key)
        except Exception:
            return None

    data = await build_docx(
        result,
        style_overrides=_style(job),
        crop_loader=crop_loader,
    )
    path = out / f"job{job.id}.docx"
    path.write_bytes(data)
    return path


def _style(job) -> dict | None:
    if not job.layout_style:
        return None
    try:
        return json.loads(job.layout_style)
    except (ValueError, TypeError):
        return None


def _docx_to_pdf(docx: Path, out: Path) -> Path | None:
    """Render bằng container LibreOffice. Không có docker CLI trong container
    (chạy script trong `docker compose exec`) → trả None + in lệnh chạy tay."""
    try:
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{out}:/data", RENDER_IMAGE, docx.name],
            check=True, capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"render tay: docker run --rm -v {out}:/data {RENDER_IMAGE} {docx.name}")
        return None
    pdf = out / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def _pdf_to_png(pdf: Path, out: Path, pages: int = 2) -> list[Path]:
    made = []
    doc = fitz.open(pdf)
    try:
        for i in range(min(pages, doc.page_count)):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
            p = out / f"docx-p{i + 1}.png"
            pix.save(p)
            made.append(p)
    finally:
        doc.close()
    return made


async def _original_pages(job, out: Path, pages: int = 2) -> list[Path]:
    storage = build_storage()
    raw = await storage.get(job.storage_key)
    made = []
    if (job.file_type or "").lower() == "pdf":
        doc = fitz.open(stream=raw, filetype="pdf")
        try:
            for i in range(min(pages, doc.page_count)):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
                p = out / f"page-p{i + 1}.png"
                pix.save(p)
                made.append(p)
        finally:
            doc.close()
    else:
        p = out / "page-p1.png"
        Image.open(__import__("io").BytesIO(raw)).save(p)
        made.append(p)
    return made


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id", type=int)
    ap.add_argument("--out", default="/tmp/docx-preview")
    ap.add_argument("--pages", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    job = await _load(args.job_id)
    docx = await _make_docx(job, out)
    pdf = _docx_to_pdf(docx, out)
    made = _pdf_to_png(pdf, out, args.pages) if pdf is not None else []
    originals = await _original_pages(job, out, args.pages)
    print(f"docx: {docx}")
    if pdf is not None:
        print(f"pdf:  {pdf} ({fitz.open(pdf).page_count} trang)")
    for p in made:
        print("word:", p)
    for p in originals:
        print("gốc:", p)


if __name__ == "__main__":
    asyncio.run(main())
