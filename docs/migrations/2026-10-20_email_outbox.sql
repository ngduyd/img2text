-- Migration 2026-10-20 — email outbox: mở rộng email_sends (audit row) thành
-- queue DB-backed. Hand-SQL (codebase có create_all, không Alembic). Idempotent.
-- Drain: app/services/email_sends.drain() qua job scheduler `flush-email-outbox`.

ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS to_email text;
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS subject text;
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS body text;
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'queued';
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS attempts int NOT NULL DEFAULT 0;
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS sent_at timestamptz;
ALTER TABLE email_sends ADD COLUMN IF NOT EXISTS last_error text;

CREATE INDEX IF NOT EXISTS email_sends_due ON email_sends (next_attempt_at)
  WHERE status = 'queued';
