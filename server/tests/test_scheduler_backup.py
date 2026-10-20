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
from sqlalchemy import func, select

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


async def test_scheduler_registers_email_outbox_and_daily_prune(app):
    """QA P3: 2 job wave-5 (flush-email-outbox, daily-prune) phải có id đã đăng ký."""
    from app.services.scheduler import init_scheduler

    init_scheduler(app)
    ids = {j.id for j in app.state.scheduler.get_jobs()}
    assert "flush-email-outbox" in ids
    assert "daily-prune" in ids


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

# --- QA-4: str-compare trigger — không reschedule khi cron không đổi ---

async def test_backup_db_reschedules_only_on_real_cron_change(app, monkeypatch):
    """QA-4: CronTrigger 3.x không có __eq__ → code cũ (`trigger != trigger`)
    reschedule MỌI tick. Cùng cron 2 tick → 0 lần; Setting đổi cron → đúng 1."""
    # không đụng pg_dump thật trong tick test
    monkeypatch.setattr(
        "app.core.db.backup_database", lambda **kw: Path("/tmp/unused.sql.gz")
    )
    from apscheduler.job import Job as APSJob

    from app.core.models import Setting
    from app.services.scheduler import init_scheduler

    scheduler = init_scheduler(app)
    job = scheduler.get_job("backup-db")
    assert job is not None

    calls: list[str] = []
    orig_reschedule = APSJob.reschedule

    def spy(self, trigger, **kw):
        calls.append(str(trigger))
        return orig_reschedule(self, trigger, **kw)

    monkeypatch.setattr(APSJob, "reschedule", spy)

    await job.func()  # tick 1: cron runtime = default = add_job trigger
    await job.func()  # tick 2: vẫn cùng cron
    assert calls == []  # bug cũ: 2 lần (identity comparison luôn khác)

    async with app.state.session_factory() as session:
        session.add(Setting(key="backup_cron", value="0 5 * * *"))
        await session.commit()
    await job.func()
    assert len(calls) == 1
    assert "hour='5'" in str(job.trigger)

async def test_prune_all_commits_deletes(app):
    """QA P2: `prune_all` chạy 4 prune trong 1 session — thiếu commit thì
    `session.close()` rollback sạch, daily-prune không xoá gì (bug cũ áp cho
    cả request_logs/page_views/refresh_tokens, không riêng email_sends)."""
    from datetime import datetime, timedelta, timezone

    from app.core.models import EmailSend, RequestLog, User
    from app.services.scheduler import init_scheduler

    old = datetime.now(timezone.utc) - timedelta(days=200)
    async with app.state.session_factory() as session:
        user = User(email="prune@test.io", password_hash="x", role="user")
        session.add(user)
        await session.flush()
        session.add_all([
            RequestLog(method="GET", path="/old", status=200, ip="127.0.0.1", ts=old),
            EmailSend(user_id=user.id, kind="welcome", created_at=old),
        ])
        await session.commit()

    scheduler = init_scheduler(app)
    await scheduler.get_job("daily-prune").func()

    async with app.state.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(RequestLog))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(EmailSend))).scalar_one() == 0
