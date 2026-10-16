# Backup & Restore (P1 spec 2026-10-15, finding #12)

## Schedule

- **In-app (mặc định):** scheduler job `backup-db` chạy daily **04:00** server
  time — `server/app/services/scheduler.py`, cron expr `backup_cron`
  (default `0 4 * * *`, pydantic settings / env `BACKUP_CRON`).
  Override runtime: ghi row `Setting(key='backup_cron', value='…')`
  (APScheduler cron expr: `min hour dom mon dow`) — job đọc mỗi tick, không
  cần restart.
- **Manual / off-schedule:** `deploy/backup.sh`

  ```bash
  DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/img2text" \
      ./deploy/backup.sh --retention 14 --output-dir /backups
  ```

## Output & retention

- File: `/backups/img2text-YYYYMMDD-HHMMSS.sql.gz` (pg_dump plain SQL, gzip).
- Retention: **14 ngày** mặc định (`backup_retention_days` env /
  `Setting(key='backup_retention_days')`; script: `--retention N`;
  `0` = giữ tất cả). Prune theo mtime, chạy sau mỗi backup thành công.
- Yêu cầu: `pg_dump` trên PATH — image đã gồm `postgres`
  client (`postgresql-client` trong `deploy/Dockerfile`); host deploy cần
  package tương đương.
- Lưu ý: `postgresql+asyncpg://` là scheme asyncpg-only — cả script lẫn
  `backup_database()` tự strip thành `postgresql://` cho libpq.

## Restore

Backup là plain SQL (pg_dump, không `--clean`) → restore vào DB TRỐNG hoặc
dùng transaction rollback để so sánh.

```bash
# 1. (khuyến nghị) DB trống để không conflict object đã tồn tại
createdb img2text_restore_check

# 2. gunzip stream vào psql — DATABASE_URL phải là scheme libpq
gunzip -c /backups/img2text-20261015-040000.sql.gz | \
  psql "postgresql://img2text:img2text@localhost:5432/img2text_restore_check"
```

Nếu `DATABASE_URL` là `postgresql+asyncpg://…` thì strip thủ công:
`${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}`.

## Test-restore checklist (chạy sau MỖI lần thay đổi backup/restore)

1. `gunzip -t /backups/<file>.sql.gz` — file không hỏng.
2. Restore vào DB scratch (`img2text_restore_check`) — psql không báo error.
3. So sánh số row bảng chính:
   `SELECT count(*) FROM users; SELECT count(*) FROM jobs;`
   (so với DB nguồn cùng thời điểm dump).
4. Login 1 user bất kỳ trên DB scratch (password hash còn nguyên).
5. Xóa DB scratch: `dropdb img2text_restore_check`.
