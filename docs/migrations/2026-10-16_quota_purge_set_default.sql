-- Migration 2026-10-16 — quota_purge server-side DEFAULT (follow-up 2026-10-15).
-- CI/CD flow: create_all TRƯỚC, migrations SAU → ADD COLUMN IF NOT EXISTS
-- no-op khi cột đã tồn tại → column_default = None (test
-- test_quota_purge_model::test_db_columns_exist_and_defaults fail: NULL ≠ 202MB).
-- ALTER COLUMN SET DEFAULT idempotent, chạy được trên cả cột create_all lẫn
-- cột do migration cũ thêm. Idempotent.
ALTER TABLE users ALTER COLUMN upload_byte_limit SET DEFAULT 211812352;
ALTER TABLE users ALTER COLUMN auto_purge SET DEFAULT true;
ALTER TABLE users ALTER COLUMN purge_notice_seen SET DEFAULT false;
ALTER TABLE jobs ALTER COLUMN upload_bytes SET DEFAULT 0;
