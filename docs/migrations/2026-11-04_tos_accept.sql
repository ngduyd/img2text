-- Migration 2026-11-04 — ToS acceptance (spec 2026-11-04, A4).
-- Hand-SQL ALTER-only (create_all never ALTERs), idempotent.

ALTER TABLE users ADD COLUMN IF NOT EXISTS tos_accepted_at TIMESTAMPTZ,
                  ADD COLUMN IF NOT EXISTS tos_version TEXT;
