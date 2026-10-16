-- 2026-10-16: kaggle session loop worker (spec
-- docs/superpowers/specs/2026-10-16-kaggle-session-worker-design.md T1).
-- worker_sessions: 1 row / Kaggle kernel session — key_hash = sha256
-- session key (hash-at-rest, P2 #16 pattern), closed_at NULL = live.
-- jobs.session_id: claim scope thay worker_token_hash (HTTP Colab path
-- giữ nguyên cột cũ). FK ON DELETE SET NULL (AC3a): close session DELETE
-- hash row NGAY (AC3/AC9) mà job đang trỏ không treo, không mất.
-- Idempotent — an toàn chạy lại (IF NOT EXISTS everywhere).

CREATE TABLE IF NOT EXISTS worker_sessions (
  id BIGSERIAL PRIMARY KEY,
  kernel_ref TEXT NOT NULL,
  key_hash TEXT NOT NULL,             -- sha256(session_key)
  spawned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ NULL,
  exit_code INT NULL,                 -- 0=graceful, 90=session-level fail
  gpu_seconds_reported DOUBLE PRECISION NOT NULL DEFAULT 0
);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS session_id BIGINT
  REFERENCES worker_sessions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_jobs_session ON jobs (session_id)
  WHERE session_id IS NOT NULL;
