"""Shared pytest fixtures for server tests.

Ruling R1: `db_session` (fresh AsyncSession, rollback after each test) and a
function-scoped truncation fixture that clears all tables between tests are
required by Tasks 2+; both are defined here for Task 1. Session-scoped
`db_schema` owns schema bootstrap: httpx.ASGITransport never runs the app
lifespan (create_all lives in main.lifespan), so a fresh Postgres volume
would otherwise hit UndefinedTable.
"""

import base64
import hashlib
import io
import os
import tempfile
from unittest.mock import AsyncMock
from uuid import uuid4

# weasyprint first-run font-cache warning must not pollute pytest output;
# point its cache at a tempdir (v70 removed the cache dir, kept for safety)
os.environ.setdefault("WEASYPRINT_CACHE_DIR", tempfile.gettempdir())

import boto3
import httpx
import pytest
import pytest_asyncio
from moto import mock_aws
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_bootstrap import bootstrap_admin
from app.services import mailer
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.main import create_app
from app.core.models import Job, User
from app.services.storage import S3Driver

# S5 gating (Lane E): middleware email-verify skip khi env=="test" —
# toàn bộ suite cũ giữ nguyên; test gating bật lại bằng monkeypatch.
settings.env = "test"

# P2 #20 (spec 2026-10-16): test gating — prod_only marker skip khi
# settings.env != "prod" (collection time, trước fixture).
def pytest_collection_modifyitems(config, items):
    if settings.env == "prod":
        return
    skip_prod = pytest.mark.skip(reason="prod_only: cần settings.env == 'prod'")
    for item in items:
        if item.get_closest_marker("prod_only") is not None:
            item.add_marker(skip_prod)

@pytest.fixture
def env(monkeypatch):
    """Override settings.env theo test (gating / middleware pattern)."""
    def _set(value: str) -> None:
        monkeypatch.setattr(settings, "env", value)
    return _set
# #9 (spec 2026-10-15): send_email TRẢ VỀ lỗi thay vì nuốt → suite phải
# hermetic: capture _send_sync thật (smtp-down tests dùng), no-op nó (mặc
# định = "gửi thành công") — test lỗi tự boom/restore tường minh.
_REAL_SEND_SYNC = mailer._send_sync

@pytest.fixture(autouse=True)
def _smtp_offline(monkeypatch):
    def _offline(*args, **kwargs):
        return None

    monkeypatch.setattr(mailer, "_send_sync", _offline)

# Test payloads shared by tests (moved from the removed test_upload.py).
def _jpeg_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
    return buf.getvalue()

def _pdf_bytes(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

TEST_JPEG = _jpeg_bytes()
TEST_PDF_3 = _pdf_bytes(3)

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "heic": "image/heic",
    "heif": "image/heif",
    "avif": "image/avif",
}

async def upload_job(
    client,
    storage,
    data: bytes,
    filename: str,
    *,
    output_format: str | None = None,
    mode: str | None = None,
    preprocess: dict | None = None,
    page_count: int | None = None,
):
    """Full presigned client flow: POST /api/jobs/presign → browser-style
    upload (storage.put == the form POST to R2) → metadata POST /api/jobs."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    sha = hashlib.sha256(data).hexdigest()
    r = await client.post(
        "/api/jobs/presign",
        json={
            "filename": filename,
            "content_type": _CONTENT_TYPES.get(ext, "application/octet-stream"),
            "size_bytes": len(data),
            "sha256": sha,
        },
    )
    assert r.status_code == 200, r.text
    key = r.json()["storage_key"]
    await storage.put(key, data)  # == the browser's form POST to storage
    if page_count is None:
        from pypdf import PdfReader

        page_count = (
            len(PdfReader(io.BytesIO(data)).pages) if ext == "pdf" else 1
        )
    body: dict = {"storage_key": key, "page_count": page_count, "filename": filename}
    if output_format is not None:
        body["output_format"] = output_format
    if mode is not None:
        body["mode"] = mode
    if preprocess is not None:
        body["preprocess"] = preprocess
    return await client.post("/api/jobs", json=body)


def _nodb(request) -> bool:
    """Marker `nodb`: test thuần hàm, không cần Postgres (chạy được khi DB tắt).

    Function-scope: xét chính test. Session-scope: chỉ bỏ khi MỌI test thu
    thập đều `nodb` (còn test khác cần DB thì fixture session vẫn chạy).
    """
    items = getattr(request.node, "items", None)
    if not items:
        return request.node.get_closest_marker("nodb") is not None
    return all(i.get_closest_marker("nodb") is not None for i in items)

@pytest_asyncio.fixture(scope="session", autouse=True)
async def db_schema(request):
    """Session-scoped: create schema ONCE against the test engine."""
    if _nodb(request):
        yield
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Fresh AsyncSession per test; rollback after each test."""
    session = SessionLocal()
    yield session
    await session.rollback()
    await session.close()


@pytest_asyncio.fixture(autouse=True)
async def db_truncate(request):
    """Function-scoped: truncate all tables between tests."""
    if _nodb(request):
        yield   # async generator: nhánh bỏ qua vẫn phải yield 1 lần
        return
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public'"
                )
            )
        ).scalars().all()
        if tables:
            await conn.execute(
                text(
                    "TRUNCATE "
                    + ", ".join(tables)
                    + " RESTART IDENTITY CASCADE"
                )
            )
    yield


async def grant_ocr(session: AsyncSession, email: str) -> None:
    """Ruling R10: enable ocr_enabled directly in DB (no admin HTTP flow)."""
    await session.execute(
        update(User).where(User.email == email).values(ocr_enabled=True)
    )
    await session.commit()

@pytest_asyncio.fixture
async def app():
    """create_app() with moto-backed S3 driver wired into app.state.storage."""
    application = create_app()
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="img2text-test"
        )
        application.state.storage = S3Driver(
            endpoint=None,
            key_id="test-key",
            secret="test-secret",
            bucket="img2text-test",
            region="us-east-1",
        )
        yield application

@pytest.fixture(autouse=True)
def proofread_llm_down(monkeypatch):
    """Proofread fires after every stored /result — keep the suite hermetic:
    its LLM seam (module-local AsyncClient, bound at import so the global
    fake_llm patches never reach it) fails fast unless a test fakes it."""
    from app.services import proofread

    class _Down:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            raise httpx.ConnectError("LLM down (tests default)")

    monkeypatch.setattr(proofread, "AsyncClient", _Down)

@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def auth_client(client, db_session):
    """Ruling R10: fresh registered+logged-in user, ocr_enabled granted."""
    email = f"u-{uuid4().hex}@test.io"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 201, r.text
    await grant_ocr(db_session, email)
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": "secret123"}
    )
    assert r.status_code == 200, r.text
    return client

@pytest_asyncio.fixture
async def admin_client(client, db_session):
    """Ruling R28: per-test bootstrap admin (AFTER truncate) + cookies.

    Register may 409 (bootstrap already created the email); login is what
    sets the access cookie.
    """
    await bootstrap_admin(db_session, "admin@test.local", "adminpass1")
    r = await client.post(
        "/api/auth/register",
        json={"email": "admin@test.local", "password": "adminpass1"},
    )
    assert r.status_code in (201, 409), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": "admin@test.local", "password": "adminpass1"},
    )
    assert r.status_code == 200, r.text
    return client

@pytest_asyncio.fixture
async def worker_client(app, monkeypatch):
    """Ruling R10: bearer-authenticated client; test runner_key value."""
    monkeypatch.setattr(settings, "runner_key", "test-runner-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-runner-key"},
    ) as c:
        yield c

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

@pytest_asyncio.fixture
async def worker_client2(app, monkeypatch):
    """Second Bearer client, same runner key (concurrency tests)."""
    monkeypatch.setattr(settings, "runner_key", "test-runner-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-runner-key"},
    ) as c:
        yield c

@pytest_asyncio.fixture
async def client_no_runner_key(app):
    """Plain client without Authorization header (runner-key 401 tests)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def upload(auth_client, app):
    """Presigned upload flow against the auth_client + moto storage."""

    async def _upload(data, filename, **kw):
        return await upload_job(auth_client, app.state.storage, data, filename, **kw)

    return _upload

@pytest_asyncio.fixture
async def seed_job(upload) -> int:
    """Real presigned upload (status queued); returns job id."""
    r = await upload(PNG_1PX, "t.png")
    assert r.status_code == 201, r.text
    return r.json()["id"]

@pytest_asyncio.fixture
def VALID_RESULT_JSONB() -> dict:
    """Spec §4 result shape: 1 page, verdicts ok + image_unextractable."""
    return {
        "model_version": "paddleocr-vl-1.5-0.9B",
        "gpu_seconds": 12.5,
        "warnings": [],
        "markdown": "# tài liệu\n\n## Phần 2",
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "page_flag": "ok",
                "markdown": "# tài liệu\n\n## Phần 2",
                "regions": [
                    {
                        "id": "r0",
                        "bbox": [1, 2, 30, 40],
                        "text": "Xin chào",
                        "verdict": "ok",
                        "placeholder": False,
                    },
                    {
                        "id": "r1",
                        "bbox": [5, 6, 70, 80],
                        "text": "",
                        "verdict": "image_unextractable",
                        "placeholder": True,
                    },
                ],
            }
        ],
    }

@pytest_asyncio.fixture
async def done_job_with_result(auth_client, db_session, VALID_RESULT_JSONB) -> int:
    """Ruling R24: done job owned by the auth_client user (uploaded state
    faked directly); returns job id."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=VALID_RESULT_JSONB,
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

@pytest_asyncio.fixture
async def storage(app):
    """Raw app.state.storage driver (no spies)."""
    return app.state.storage

@pytest_asyncio.fixture
async def storage_spy(app):
    """Ruling R10: wrap app.state.storage driver methods; real op still runs."""
    driver = app.state.storage
    for name in ("put", "exists", "presign_get", "delete_prefix", "get"):
        setattr(driver, name, AsyncMock(wraps=getattr(driver, name)))
    yield driver
