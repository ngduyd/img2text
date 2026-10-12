-- Migration 2026-10-13 — quota + admin LLM (spec 2026-10-13, Assumption #4-5)
-- Hand-SQL (ALTER-only — codebase có create_all, không Alembic). Idempotent.
-- Cột nullable (DEFAULT backfill mọi row cũ = 25/150); model User.daily_page_limit
-- / weekly_page_limit là Mapped[int | None] — reader fallback qua
-- app.services.quota.limit_of() (NULL → default).
-- Admin LLM (llm_timeout/llm_api_key): KHÔNG cần DDL — runtime override qua
-- bảng settings (Setting rows), env chỉ là default.

ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_page_limit int DEFAULT 25;
ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_page_limit int DEFAULT 150;
