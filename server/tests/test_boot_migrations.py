"""Boot migrations (M1/M2): apply docs/migrations/*.sql at startup.

(a) fresh DB → applies every .sql, returns filenames;
(b) second run → no-op ([]);
(c) recorded sha tampered → RuntimeError (frozen-migration guard);
(d) missing dir → warning + [] (dev box without docs/).
"""

import hashlib
import logging
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text

from app.core.db import engine
from app.core.migrations import _connect_kwargs, _migrations_dir, apply_migrations

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

# F1 (#2): the SQL-file execute and the schema_migrations INSERT must share one
# transaction. Discriminator: the file itself inserts its OWN row with a bogus
# sha; the follower INSERT then hits the PK. With per-pair atomicity the whole
# thing (file's table + bogus row) rolls back; without it the bogus row sticks.
async def test_failed_file_rolls_back_its_record(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    probe = f"f1_probe_{uuid.uuid4().hex[:8]}"
    (tmp_path / "f1_bad.sql").write_text(
        f"CREATE TABLE IF NOT EXISTS {probe} (id int);\n"
        "INSERT INTO schema_migrations (filename, sha256) "
        "VALUES ('f1_bad.sql', 'bogus');\n"
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await apply_migrations(engine)
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                text("SELECT filename FROM schema_migrations WHERE filename='f1_bad.sql'")
            )
        ).scalars().all()
        still_there = (
            await conn.execute(text(f"SELECT to_regclass('public.{probe}')"))
        ).scalar()
    assert rows == []
    assert still_there is None

# F2 (#3): a new file sorting BEFORE a drifted one must not be applied — the
# whole-set sha validation runs first and raises before any apply pass.
async def test_drift_aborts_before_new_file_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    (tmp_path / "b_drift.sql").write_text("CREATE TABLE IF NOT EXISTS f2_b (id int);")
    assert await apply_migrations(engine) == ["b_drift.sql"]
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE schema_migrations SET sha256='tampered' "
                 "WHERE filename='b_drift.sql'")
        )
    (tmp_path / "a_new.sql").write_text("CREATE TABLE IF NOT EXISTS f2_a (id int);")
    with pytest.raises(RuntimeError, match="modified after apply"):
        await apply_migrations(engine)
    async with engine.begin() as conn:
        names = (
            await conn.execute(text("SELECT filename FROM schema_migrations"))
        ).scalars().all()
    assert "a_new.sql" not in names

# F3 (#4): asyncpg gets components, not a DSN — a DSN string mangles reserved
# chars (@ : /) in the password. make_url decodes the percent-encoded userinfo.
def test_connect_kwargs_decodes_special_password():
    kwargs = _connect_kwargs(
        "postgresql+asyncpg://img2text:p%40ss%3Aw%2Frd@db.example:5433/img2text_test"
    )
    assert kwargs == {
        "host": "db.example",
        "port": 5433,
        "user": "img2text",
        "password": "p@ss:w/rd",
        "database": "img2text_test",
    }
