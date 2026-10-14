-- Migration 2026-10-15 — feedbacks (wave-5 S6, Lane B2).
-- Hand-SQL (codebase có create_all, không Alembic). Idempotent.

CREATE TABLE IF NOT EXISTS feedbacks (
  id bigserial PRIMARY KEY,
  user_id int NULL REFERENCES users(id) ON DELETE SET NULL,
  content text NOT NULL,
  page_path text NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_feedbacks_created_at ON feedbacks (created_at);
