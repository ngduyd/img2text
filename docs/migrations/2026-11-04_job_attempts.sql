-- Migration 2026-11-04 — jobs.attempts (spec 2026-11-04, B3): đếm số lần
-- reap requeue; chạm job_max_attempts → failed. Idempotent, ALTER-only.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
