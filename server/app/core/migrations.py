"""Boot-time schema migrations: apply docs/migrations/*.sql after create_all.

create_all only creates missing tables — it never ALTERs an existing one, so a
deployed DB (prod/dev) booted without the CI `psql` step hits
`column ... does not exist`. `apply_migrations` runs right after create_all in
lifespan and applies any un-applied `.sql` (raw, multi-statement via asyncpg).

Tracking: `schema_migrations(filename, sha256, applied_at)`. Applied + sha
match → skip; sha drift → RuntimeError (frozen migration guard); new → apply
then record. Missing dir → warning + no-op (dev box without docs/).

F1: file SQL + its tracking row share ONE transaction. F2: validate all shas
before applying any file.
"""

import hashlib
import logging
import os
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

_CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   text PRIMARY KEY,
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _migrations_dir() -> Path:
    """env MIGRATIONS_DIR wins; else repo-relative to this file
    (server/app/core/migrations.py → parents[3]/docs/migrations)."""
    env = os.environ.get("MIGRATIONS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "docs" / "migrations"


def _connect_kwargs(url) -> dict[str, object]:
    """asyncpg gets connection components, not a DSN: a DSN string mangles
    reserved chars (@ : /) in the password (F3). make_url decodes the
    percent-encoded userinfo; forward the parsed pieces."""
    u = make_url(url) if isinstance(url, str) else url
    return {
        "host": u.host,
        "port": u.port,
        "user": u.username,
        "password": u.password,
        "database": u.database,
    }


async def apply_migrations(engine) -> list[str]:
    """Apply un-applied `*.sql` (sorted by name) → list of filenames applied.

    ponytail: no cross-replica lock — ceiling = single uvicorn worker (prod
    today). Two replicas booting together could double-apply. Add when we run
    >1 worker: wrap the whole thing in `pg_advisory_lock(<const>)` (session
    lock on a dedicated connection, released in `finally`).
    """
    directory = _migrations_dir()
    if not directory.is_dir():
        logger.warning("migrations dir missing: %s — skipping", directory)
        return []

    files = sorted(directory.glob("*.sql"))
    applied: list[str] = []
    conn = await asyncpg.connect(**_connect_kwargs(engine.url))
    try:
        await conn.execute(_CREATE_TRACKING)
        recorded = {
            row["filename"]: row["sha256"]
            for row in await conn.fetch(
                "SELECT filename, sha256 FROM schema_migrations"
            )
        }
        # F2: validate EVERY file's sha first — a new file sorting ahead of a
        # drifted one must not be applied before we raise.
        shas = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        }
        for name, sha in shas.items():
            prev = recorded.get(name)
            if prev is not None and prev != sha:
                raise RuntimeError(
                    f"migration {name} modified after apply "
                    f"(recorded {prev[:12]}…, file {sha[:12]}…)"
                )
        for path in files:
            if path.name in recorded:
                continue
            # F1: file SQL + its schema_migrations row share ONE transaction —
            # a crash between the two rolls back the file too, so the next boot
            # re-applies cleanly instead of recording an un-applied file.
            async with conn.transaction():
                # Simple query (no params) → asyncpg allows multi-statement SQL.
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO schema_migrations (filename, sha256) "
                    "VALUES ($1, $2)",
                    path.name,
                    shas[path.name],
                )
            applied.append(path.name)
    finally:
        await conn.close()
    return applied
