-- Migration 2026-10-15 — quota bytes upload 7 ngày + purge file gốc (wave-5 S1)
-- Hand-SQL (ALTER-only — codebase có create_all, không Alembic). Idempotent.
-- upload_byte_limit DEFAULT 211812352 (202MB) — backfill mọi row cũ; model
-- Mapped[int | None], reader fallback quota.limit_of() (NULL → default).

ALTER TABLE users ADD COLUMN IF NOT EXISTS upload_byte_limit bigint DEFAULT 211812352;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_purge bool DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS purge_notice_seen bool DEFAULT false;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS upload_bytes bigint NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS storage_purged_at timestamptz NULL;
