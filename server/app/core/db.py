"""Async engine, session factory, and the `get_session` dependency.

Schema bootstrap (Base.metadata.create_all) lives in main.lifespan — R1:
httpx ASGITransport skips lifespan, tests create schema from the same Base.
"""

import gzip
import shutil
import subprocess
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

def backup_database(
    output_dir: str | Path = "/backups",
    retention_days: int | None = None,
    database_url: str | None = None,
) -> Path:
    """#12 (spec 2026-10-15): pg_dump → img2text-YYYYMMDD-HHMMSS.sql.gz,
    prune cũ hơn retention_days (default settings.backup_retention_days).

    libpq không hiểu scheme postgresql+asyncpg:// → strip suffix.
    Streaming gzip (dump không load hết vào RAM). pg_dump thiếu / exit≠0 →
    RuntimeError — scheduler job log, một pass lỗi không giết tick.
    """
    url = database_url or settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"img2text-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sql.gz"
    try:
        # stderr=PIPE đọc SAU khi stdout xong — pg_dump stderr chỉ báo lỗi
        # (ngắn); nếu bao giờ nó viết >64KB stderr thì chuyển DEVNULL.
        proc = subprocess.Popen(
            ["pg_dump", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError as e:
        raise RuntimeError("pg_dump not found — install postgresql-client") from e
    assert proc.stdout is not None and proc.stderr is not None
    with dest.open("wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb") as gz:
        shutil.copyfileobj(proc.stdout, gz)
    stderr = proc.stderr.read()
    rc = proc.wait()
    if rc != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"pg_dump failed ({rc}): {stderr.decode(errors='replace')[:500]}"
        )
    days = (
        settings.backup_retention_days if retention_days is None else retention_days
    )
    _prune_backups(out, days)
    return dest

def _prune_backups(out: Path, days: int) -> int:
    """Xoá backup img2text-*.sql.gz cũ hơn `days` theo mtime; days<=0 = giữ
    tất cả."""
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for old in out.glob("img2text-*.sql.gz"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            removed += 1
    return removed
