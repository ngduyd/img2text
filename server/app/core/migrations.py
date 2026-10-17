"""Boot-time schema migrations: apply docs/migrations/*.sql after create_all.

create_all only creates missing tables — it never ALTERs an existing one, so a
deployed DB (prod/dev) booted without the CI `psql` step hits
`column ... does not exist`. `apply_migrations` runs right after create_all in
lifespan and applies any un-applied `.sql` (raw, multi-statement via asyncpg).

Tracking: `schema_migrations(filename, sha256, applied_at)`. Applied + sha
match → skip; sha drift → RuntimeError (frozen migration guard); new → apply
then record. Missing dir → warning + no-op (dev box without docs/).
"""

import hashlib
import logging
import os
from pathlib import Path

import asyncpg

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


def _dsn(engine) -> str:
    """libpq/asyncpg don't understand the +asyncpg SQLAlchemy scheme."""
    url = engine.url.render_as_string(hide_password=False)
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def apply_migrations(engine) -> list[str]:
    """Apply un-applied `*.sql` (sorted by name) → list of filenames applied."""
    directory = _migrations_dir()
    if not directory.is_dir():
        logger.warning("migrations dir missing: %s — skipping", directory)
        return []

    files = sorted(directory.glob("*.sql"))
    applied: list[str] = []
    conn = await asyncpg.connect(_dsn(engine))
    try:
        await conn.execute(_CREATE_TRACKING)
        recorded = {
            row["filename"]: row["sha256"]
            for row in await conn.fetch(
                "SELECT filename, sha256 FROM schema_migrations"
            )
        }
        for path in files:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            prev = recorded.get(path.name)
            if prev is not None:
                if prev != sha:
                    raise RuntimeError(
                        f"migration {path.name} modified after apply "
                        f"(recorded {prev[:12]}…, file {sha[:12]}…)"
                    )
                continue
            # Simple query (no params) → asyncpg allows multi-statement SQL.
            await conn.execute(path.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations (filename, sha256) "
                "VALUES ($1, $2)",
                path.name,
                sha,
            )
            applied.append(path.name)
    finally:
        await conn.close()
    return applied
