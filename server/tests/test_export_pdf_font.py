"""#9 smoke: pdf export tiếng Việt không rớt dấu — bytes>0 + /Font nhúng.

Skip-with-reason (không weaken) khi env thiếu weasyprint hoặc pandoc —
CI/empty image không có tool thì KHÔNG chứng minh được gì.
"""

import importlib.util
import io
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.models import Job, User

def _pandoc_available() -> bool:
    from app.services.convert import PANDOC_BIN

    return Path(PANDOC_BIN).is_file() or shutil.which("pandoc") is not None

_SKIP = pytest.mark.skipif(
    importlib.util.find_spec("weasyprint") is None or not _pandoc_available(),
    reason="cần weasyprint + pandoc local để smoke export pdf (env thiếu)",
)

def test_dockerfile_has_dejavu_fonts_and_fontconfig():
    """Dockerfile server: fonts-dejavu (extra bold/italic) + fontconfig —
    chặn image 'mở được nhưng rớt dấu' (spec 2026-10-14 #9). Chạy mọi env."""
    src = (Path(__file__).parents[2] / "deploy" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "fonts-dejavu-extra" in src
    assert "fontconfig" in src

@pytest_asyncio.fixture
async def done_vietnamese_job(auth_client, db_session, storage) -> int:
    markdown = (
        "# Hồ sơ năng lượng tái tạo\n\n"
        "Ngân hàng Nhà nước Việt Nam — quyết định số 12/2026/QĐ-NHNN.\n\n"
        "## bilingual / song ngữ\n\n"
        "Đường sắt Bắc Nam: 1.726 km. English: quarterly report Q4.\n"
    )
    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result={
            "model_version": "paddleocr-vl-1.5-0.9B",
            "gpu_seconds": 1.0,
            "warnings": [],
            "markdown": markdown,
            "pages": [{"index": 0, "width": 200, "height": 400,
                       "page_flag": "ok", "markdown": markdown,
                       "regions": []}],
        },
        storage_key="uploads/vn.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

@_SKIP
async def test_pdf_vietnamese_embeds_font(
    auth_client, done_vietnamese_job, storage
):
    r = await auth_client.post(
        f"/api/jobs/{done_vietnamese_job}/export", json={"fmt": "pdf"}
    )
    assert r.status_code == 200, r.text
    data = await storage.get(f"exports/{done_vietnamese_job}/pdf")
    assert len(data) > 0 and data.startswith(b"%PDF")

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    basefonts: set[str] = set()
    for page in reader.pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else {}
        fdict = res.get("/Font")
        fdict = fdict.get_object() if fdict is not None else {}
        for ref in (fdict or {}).values():
            fo = ref.get_object()
            basefonts.add(str(fo.get("/BaseFont") or ""))
    assert basefonts, "/Font dict rỗng — file mở được nhưng rớt dấu font"
    assert any("DejaVu" in b for b in basefonts), basefonts
