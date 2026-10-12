# Migration 2026-10-14 — worker_heartbeats (wave-2 #7)

Hand-SQL (`CREATE TABLE IF NOT EXISTS` — codebase có create_all, không Alembic):

```sql
CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id text PRIMARY KEY,
  kind text,
  last_seen timestamptz NOT NULL,
  current_job_id int null
);
```

Model `app.core.models.WorkerHeartbeat` — test DB tạo qua `create_all`.
kind: `"loop"` (Colab loop, `POST /api/worker/heartbeat` runner-key) |
`"kaggle-batch"` (orchestrator upsert khi spawn + mỗi poll).

Trạng thái áp dụng:

| DB | Áp dụng |
|---|---|
| test `img2text_test` @ :5436 | ✅ 2026-10-14 (create_all) |
| dev `img2text_dev` @ :5433 | ⏳ deploy lane |
| prod | ⏳ deploy lane |
