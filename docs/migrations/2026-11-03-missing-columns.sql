-- 2026-11-03: bổ sung cột/bảng còn thiếu so với models.py
-- Lý do: create_all KHÔNG bao giờ ALTER — các DB tạo trước khi thêm
-- cột/bảng này sẽ thiếu chúng. Migration idempotent (IF NOT EXISTS)
-- an toàn chạy lại trên mọi env.
--
-- Đối chiếu 2026-11-03: cột đã có .sql thì KHÔNG lặp lại ở đây
-- (daily/weekly_page_limit, upload_byte_limit/auto_purge/purge_notice_seen,
-- upload_bytes/storage_purged_at, session_id, worker_token_hash, is_verified,
-- password_reset_code).

-- User.ocr_enabled: Boolean NOT NULL DEFAULT false
ALTER TABLE users ADD COLUMN IF NOT EXISTS ocr_enabled BOOLEAN NOT NULL DEFAULT false;

-- Job.preprocess: nullable Text
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS preprocess TEXT;

-- Job.output_format: nullable Text DEFAULT 'md'
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS output_format TEXT DEFAULT 'md';

-- Job.layout_style: nullable Text
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS layout_style TEXT;

-- Job.filename: nullable Text (chỉ có .md — 2026-10-14-jobs-filename.md)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS filename TEXT;

-- Job.mode: Phase 5 — "layout" (default) | "extract_only"
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'layout';

-- Job.text_version: optimistic lock cho POST /extraction
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS text_version INT NOT NULL DEFAULT 0;

-- Job.rerender_requested: text save khi rendering → render lại 1 lần
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rerender_requested BOOLEAN NOT NULL DEFAULT false;

-- Job.kaggle_ref / failed_step: adopt batch sau restart + retry target
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kaggle_ref TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_step TEXT;

-- Job.ir_json: Document IR JSON (IR rewrite)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ir_json TEXT;

-- WorkerHeartbeat table: 1 row/worker_id, upsert liveness
CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  kind TEXT,
  last_seen TIMESTAMPTZ NOT NULL,
  current_job_id INT NULL
);