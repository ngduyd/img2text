# Migration 2026-10-13 — users quota limits (WS-ADMIN, spec item 19)

Hand-SQL (ALTER-only — codebase có create_all, không Alembic):

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_page_limit int DEFAULT 25;
ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_page_limit int DEFAULT 150;
```

Cột nullable (DEFAULT backfill mọi row cũ = 25/150); model `User.daily_page_limit`
/ `weekly_page_limit` là `Mapped[int | None]` — reader fallback qua
`app.services.quota.limit_of()` (NULL → default).

Trạng thái áp dụng:

| DB | Áp dụng |
|---|---|
| test `img2text_test2` @ :5436 | ✅ 2026-10-13 (lane C) |
| dev `img2text_dev` @ :5433 | ⏳ deploy lane |
| prod | ⏳ deploy lane |
