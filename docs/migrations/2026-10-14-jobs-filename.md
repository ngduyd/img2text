# Migration 2026-10-14 — jobs.filename (wave-2 #3 search)

Hand-SQL (ALTER-only — codebase có create_all, không Alembic):

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS filename TEXT;
```

Cột nullable: client khai tên file gốc khi `POST /api/jobs`
(`JobCreateBody.filename` optional) → `GET /api/jobs?q=` ILIKE.
Legacy rows NULL → q không khớp (accept, spec wave-2 #3).
Metadata only — route validate (`_clean_filename`) không bao giờ làm path.

Trạng thái áp dụng:

| DB | Áp dụng |
|---|---|
| test `img2text_test` @ :5436 | ✅ 2026-10-14 (wave-2 lane) |
| dev `img2text_dev` @ :5433 | ⏳ deploy lane |
| prod | ⏳ deploy lane |
