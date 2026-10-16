"""#12 (spec 2026-10-15): backup-db scheduler job + backup_database helper.

Mock scheduler (init_scheduler không start dưới pytest) + fake pg_dump trên
PATH — test logic (scheme strip, gzip, prune, lỗi pg_dump) không cần binary
thật.
"""

import gzip
import os
import time
from pathlib import Path

import pytest

from app.core.db import backup_database

_ASYNCPG_URL = "postgresql+asyncpg://img2text:secret@localhost:5436/img2text"
_LIBPQ_URL = "postgresql://img2text:secret@localhost:5436/img2text"


def _fake_pg_dump(tmp_path: Path, monkeypatch, script: str) -> None:
    fake = tmp_path / "pg_dump"
    fake.write_text(script)
    fake.chmod(0o755)
    # PATH trùng tên trước PATH thật — fake thắng resolve; monkeypatch
    # tự restore sau test (không leak PATH ra session)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")


async def test_backup_db_job_registered_daily_0400(app):
    from app.services.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    job = scheduler.get_job("backup-db")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "4" and fields["minute"] == "0"
    # cùng tick với daily-prune (03:00) — không dẫm nhau: job id riêng
    assert job.id == "backup-db"


def test_backup_database_writes_gzipped_dump(tmp_path, monkeypatch):
    # echo "$1" = assert connstring truyền cho pg_dump
    _fake_pg_dump(tmp_path, monkeypatch, '#!/bin/sh\necho "$1"\n')
    dest = backup_database(
        output_dir=tmp_path / "backups",
        retention_days=14,
        database_url=_ASYNCPG_URL,
    )
    # libpq scheme: +asyncpg stripped
    assert gzip.decompress(dest.read_bytes()).decode() == _LIBPQ_URL + "\n"
    assert dest.parent == tmp_path / "backups"
    assert dest.name.startswith("img2text-") and dest.name.endswith(".sql.gz")


def test_backup_database_prunes_old_backups(tmp_path, monkeypatch):
    _fake_pg_dump(tmp_path, monkeypatch, '#!/bin/sh\necho SQL\n')
    out = tmp_path / "backups"
    out.mkdir()
    stale = out / "img2text-20200101-000000.sql.gz"
    stale.write_bytes(b"old")
    stale_mtime = time.time() - 20 * 86400  # 20 ngày trước > retention 14
    os.utime(stale, (stale_mtime, stale_mtime))
    dest = backup_database(output_dir=out, retention_days=14)
    assert not stale.exists()
    assert dest.exists()


def test_backup_database_raises_on_pg_dump_failure(tmp_path, monkeypatch):
    _fake_pg_dump(tmp_path, monkeypatch, '#!/bin/sh\necho "boom" >&2\nexit 1\n')
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        backup_database(output_dir=tmp_path / "backups")
    # dump hỏng không để lại file
    assert list((tmp_path / "backups").glob("*.sql.gz")) == []
