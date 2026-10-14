# Spec: Wave-5 — email verify + quota/purge + i18n + feedback + landing v2 + rate-limit (2026-10-15)

Base: master `095e691`. User-approval từ brainstorming chat (từng mục).

## S1 — Quota upload 201MB/7d + purge binary (Lane M1, server)

**Rulings**: reject (429) không auto-evict; purge = binary only, GIỮ layout; rolling window 7×24h.

- Migration `docs/migrations/2026-10-15_quota_purge.sql`:
  `users.upload_byte_limit bigint DEFAULT 211812352` · `users.auto_purge bool DEFAULT true` ·
  `users.purge_notice_seen bool DEFAULT false` · `jobs.upload_bytes bigint NOT NULL DEFAULT 0` ·
  `jobs.storage_purged_at timestamptz NULL`
- Create job: ghi bytes thật (file size), check `SUM(upload_bytes) WHERE user_id AND created_at>now-7d AND upload_bytes>0` + bytes mới > limit → 429 `{code:"upload_quota", used_bytes, limit_bytes, oldest_expires_at}`. Refund bytes khi job failed/cancelled (set upload_bytes=0, pattern refund page quota).
- Scheduler job mới `purge-storage` hourly (interval runtime key `purge_interval_seconds`, default 3600): batch `created_at < now-retention_days` (default 7, runtime setting `purge_retention_days`) AND `auto_purge` AND `storage_purged_at IS NULL` AND status done → delete `storage_key` + `exports/{id}/pdf` + `exports/{id}/docx` (regen được) → set `storage_purged_at`. **GIỮ** crops, md-layout, docx.html, versions, job row.
- `POST /api/jobs/{id}/purge-storage` (user chủ động, opt-in) — cùng logic.
- Guard: retry OCR / re-render VLM khi `storage_purged_at` → 410 `{code:"purged"}`. Edit/export text bình thường.
- Serializer: thêm `upload_bytes`, `storage_purged_at`.
- First-upload notice: modal 1 lần (không toast) "File gốc sẽ tự xóa sau N ngày. Bạn có thể tắt trong Cài đặt." → dismiss PATCH `purge_notice_seen`.
- Settings page: toggle auto-purge (PUT /api/auth/me `{auto_purge}` hoặc settings endpoint phù hợp).
- Web: quota badge % wizard, 429 hiện dùng/limit/thời điểm trôi, badge "file gốc đã hết hạn" trên File gốc.

## S5 — Email verify + reset code + limits (Lane E, server)

**Rulings**: register → welcome KHÁC mã verify; chưa verify = gate toàn app (modal, không toast); verify + reset = mã 6 số TTL 5p; limits per-type.

- Migration: `users.is_verified bool DEFAULT false`, `users.email_verify_expires_at`, `users.password_reset_expires_at`, `users.password_reset_code` (hash), cột verify code hash + expiry. Bảng `email_sends(id, user_id, kind, created_at)`.
- Register: tạo user (is_verified=false) → send welcome email + verify email (mã 6 số, TTL 5p, hash lưu DB). Luôn 201 (không leak tồn tại).
- Verify: `POST /api/auth/verify {code}` — hash compare, hết hạn/sai → 422. Đúng → is_verified=true.
- Resend: `POST /api/auth/verify/resend` — qua email limit.
- Forgot: đổi từ token-link → mã 6 số TTL 5p (hash). `POST /api/auth/password/reset {code, password}`.
- **Email limit** (mỗi kind riêng: welcome/verify_code/reset_code): max 5/ngày/user (rolling 24h, bảng email_sends); spacing: send #1-3 ≥10 phút, #4-5 ≥1 giờ. Vượt → 429 `{code:"email_limit", retry_after_seconds}`. Áp TRƯỚC enqueue.
- **Gating**: middleware/deps — mọi API ngoài `/api/auth/(register|login|verify|verify/resend|password/forgot|password/reset)` + `/api/healthz` khi `is_verified=false` → 403 `{code:"email_unverified"}`. Admin bypass.
- Web: Modal verify toàn màn hình (không dismiss): ô 6 số + countdown TTL + "Gửi lại mã" + logout link. Route guard: mọi trang app ngoài login/register → hiện modal. Client 403 `email_unverified` → mở modal.
- Email content EN, plain text.

## S6 — Feedback (Lane F, full)

- Migration: `feedbacks(id, user_id nullable, content text, page_path, created_at)`.
- `POST /api/feedback {content, page_path}` (auth, max 2000 chars) → lưu.
- Web: trang `/feedback` form (textarea + submit + toast R59). Link ở footer/nav.
- `GET /api/admin/feedbacks` (admin, phân trang) + `/admin/feedbacks` trang list.

## S7 — Footer (Lane B1, web)

- Footer toàn trang: "© 2026 Nguyen Duy" · mailto `nguyenduy2004.d@gmail.com` · `https://ngduyd.id.vn` (blank+noopener) · link /feedback. i18n keys footer.*.

## S8 — Trang "In the feature" — tính năng bản kế tiếp (Lane B1, web)

**User correction (2026-10-15): KHÔNG redesign landing — trang RIÊNG `/features`.**

- Route `/features` + Nav link. Hero "In the feature · Coming soon".
- Nội dung: **Organizations (Tổ chức)** — teams tạo không gian riêng, org admin tự cấu hình GPU worker pool + storage server (R2/S3 riêng) cho org, quota chung, member management.
- 3 feature cards: Custom worker pools, Org-level storage, Shared quotas & members (badge "Soon", icon inline SVG, không ảnh bitmap).
- Taste skill design-taste-frontend; responsive; i18n keys features.*.

## S2 — i18n vi/en (Lane M3, web)

- Custom hook `useT` (~60 dòng) + `src/i18n/en.json` + `vi.json` — không thêm dependency.
- Nút switch VI/EN: Nav + Landing header + Settings; `localStorage("lang")`, default "en".
- Toàn bộ string web: pages, components, toasts (R59), errors, aria-label, placeholders → keys (dot-namespaced).
- Server errors có thể dịch: API trả `{code, params}` (S1/S5 đã có) → web map code→key; fallback hiển thị detail.
- Tests: default en; update assertions.
- Deferred: footer/landing strings viết thẳng key, M3 điền dict — hoặc L viết key placeholder en.json. QUYẾT ĐỊNH: M3 làm infra + các trang cũ; L/F dùng `useT` với key riêng, dict do chính lane bổ sung.

## R — Rate-limit 1s/1req per browser (Lane R, server)

- In-memory (dict) sliding limiter: key = (client IP, User-Agent hash) → min interval 1s. Violation → 429 `{code:"rate_limited"}`.
- Áp global cho auth endpoints (register/login/verify/forgot/reset/feedback). Bỏ qua khi `settings.env==test`.
- ponytail: in-memory, restart reset — upgrade Redis khi multi-instance.

## S3 — Admin config UI full sections: DEFERRED (user bảo để sau).

## Lane order

```
Wave A (merged): M1 quota+purge ∥ E email ∥ M3 i18n — master 2841330
Wave B (parallel): B1 footer+features ∥ B2 feedback ∥ B3 admin storage
Wave C: R rate-limit
```
