"""Boot migrations (M1/M2): apply docs/migrations/*.sql at startup.

(a) fresh DB → applies every .sql, returns filenames;
(b) second run → no-op ([]);
(c) recorded sha tampered → RuntimeError (frozen-migration guard);
(d) missing dir → warning + [] (dev box without docs/).
"""

import hashlib
import logging
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.core.migrations import _migrations_dir, apply_migrations

SQL_DIR = Path(__file__).resolve().parents[2] / "docs" / "migrations"
EXPECTED = sorted(p.name for p in SQL_DIR.glob("*.sql"))


async def test_applies_all_on_fresh_db():
    applied = await apply_migrations(engine)
    assert applied == EXPECTED
    async with engine.begin() as conn:
        rows = (
            await conn.execute(text("SELECT filename, sha256 FROM schema_migrations"))
        ).all()
    assert {r.filename for r in rows} == set(EXPECTED)
    first = SQL_DIR / EXPECTED[0]
    stored = dict(rows)[EXPECTED[0]]
    assert stored == hashlib.sha256(first.read_bytes()).hexdigest()


async def test_second_run_is_noop():
    assert await apply_migrations(engine) == EXPECTED
    assert await apply_migrations(engine) == []


async def test_sha_drift_raises():
    applied = await apply_migrations(engine)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE schema_migrations SET sha256 = 'tampered' WHERE filename = :f"),
            {"f": applied[0]},
        )
    with pytest.raises(RuntimeError, match="modified after apply"):
        await apply_migrations(engine)


async def test_missing_dir_warns_and_skips(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path / "nope"))
    assert not _migrations_dir().is_dir()
    with caplog.at_level(logging.WARNING):
        assert await apply_migrations(engine) == []
    assert "migrations dir missing" in caplog.text
