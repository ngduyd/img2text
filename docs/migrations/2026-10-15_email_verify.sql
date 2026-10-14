-- Migration 2026-10-15 — email verify + reset code + email_sends audit
-- (spec wave-5 S5, Lane E). Hand-SQL ALTER-only (create_all never ALTERs),
-- idempotent. Test DB img2text_test@5436 đã apply.

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified boolean NOT NULL DEFAULT false;
-- sha256 hex của mã 6 số; TTL 5 phút (email_verify_expires_at). Single active
-- code/user: resend/forgot ghi đè.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_code_hash text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_expires_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_code text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at timestamptz;

-- Audit outbound email: mỗi kind (welcome|verify_code|reset_code) max 5/24h
-- rolling + spacing 10'/1h — check TRƯỚC khi enqueue (app/services/email_sends.py).
CREATE TABLE IF NOT EXISTS email_sends (
  id bigserial PRIMARY KEY,
  user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_email_sends_user_kind_created
  ON email_sends (user_id, kind, created_at);

-- S5: forgot đổi token-link → mã 6 số (hash trên users) — bảng token bỏ dùng.
DROP TABLE IF EXISTS password_reset_tokens;
