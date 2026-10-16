-- Migration 2026-10-16 — worker_token hash-at-rest (P2 #16, spec
-- 2026-10-16-p2-prod-hardening). Hand-SQL (codebase có create_all, không
-- Alembic). Idempotent — chạy lại được (CI/CD flow: create_all TRƯỚC →
-- ADD no-op, backfill DO-guard skip, DROP IF EXISTS no-op).
-- Checksum: sha256(file) pin trong server/tests/test_migration_p2_worker_token.py
-- (tamper-detection — file apply prod không được sửa lặng).
-- pgcrypto: digest() = SHA-256 hex cho backfill (trusted extension PG13+,
-- DB owner cài được; CREATE EXTENSION IF NOT EXISTS idempotent).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_token_hash TEXT;

-- Backfill plaintext còn sót (job đang claim dở) TRƯỚC khi DROP cột cũ.
-- Guard: cột worker_token không tồn tại (re-run / schema create_all mới)
-- → skip backfill (UPDATE tham chiếu cột thiếu sẽ lỗi parse/execute).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'jobs'
      AND column_name = 'worker_token'
  ) THEN
    EXECUTE 'UPDATE jobs
             SET worker_token_hash =
                 encode(digest(worker_token, ''sha256''), ''hex'')
             WHERE worker_token IS NOT NULL
               AND worker_token_hash IS NULL';
  END IF;
END $$;

ALTER TABLE jobs DROP COLUMN IF EXISTS worker_token;
