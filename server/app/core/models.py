"""SQLAlchemy ORM models (Task 2): users, tokens, jobs, analytics, settings.

Spec §4 shapes: Job carries storage_key/file_type/page_count/preprocess/
result; worker_token_hash = sha256(plaintext) per ruling R11 (P2 #16
hash-at-rest, migration 2026-10-16_worker_token_hash.sql).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="user")
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # WS-ADMIN quota (spec 2026-10-13): trang/ngày (local Asia/Ho_Chi_Minh)
    # và trang/tuần (T2→CN). Nullable ALTER-only (create_all never ALTERs):
    #   ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_page_limit INT DEFAULT 25;
    #   ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_page_limit INT DEFAULT 150;
    # Readers fall back via app.services.quota.limit_of() (legacy NULL rows).
    daily_page_limit: Mapped[int | None] = mapped_column(Integer, default=25)
    weekly_page_limit: Mapped[int | None] = mapped_column(Integer, default=150)
    # Wave-5 S5: email verify (is_verified=false → gating 403 email_unverified);
    # *_code_hash = sha256 hex của mã 6 số, TTL 5 phút, single active code/user
    # (resend/forgot ghi đè). Migration ALTER-only:
    #   docs/migrations/2026-10-15_email_verify.sql
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    email_verify_code_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verify_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_reset_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Wave-5 S1 (spec 2026-10-15): quota bytes upload 7 ngày + purge file gốc.
    # ALTER-only migration (create_all never ALTERs):
    #   docs/migrations/2026-10-15_quota_purge.sql
    # upload_byte_limit nullable legacy → reader fallback limit_of() (202MB).
    upload_byte_limit: Mapped[int | None] = mapped_column(BigInteger, default=211812352)
    auto_purge: Mapped[bool | None] = mapped_column(Boolean, default=True)
    purge_notice_seen: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# S5 wave-5: PasswordResetToken (token-link) bỏ — forgot/reset dùng mã
# 6 số hash trên users (password_reset_code/_expires_at); migration
# 2026-10-15_email_verify.sql DROP TABLE password_reset_tokens.

class EmailSend(Base):
    """Wave-5 S5 audit: 1 row / outbound email. Kinds: welcome |
    verify_code | reset_code. Per-kind limits (5/24h rolling + spacing
    10'/1h) đọc bảng này — app/services/email_sends.py.

    Hand-SQL migration (dev/test đã apply; create_all tạo trong test volume):
      CREATE TABLE email_sends (
        id bigserial PRIMARY KEY,
        user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
      );
    """

    __tablename__ = "email_sends"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

class Feedback(Base):
    """Wave-5 S6 (Lane B2): user feedback. user_id nullable (anon form
    không dùng — POST auth, nhưng cột nullable cho import tay).
    Hand-SQL migration (test DB đã apply; create_all tạo trong test volume):
      docs/migrations/2026-10-15_feedback.sql
    """

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text)
    page_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

class PageView(Base):
    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    method: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    status: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip: Mapped[str] = mapped_column(String)
    ua: Mapped[str | None] = mapped_column(String, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)

class Job(Base):
    """OCR job (spec §4). user_id FK plain, no cascade (spec §4).
    P2 #16: worker_token hash-at-rest (ruling R11 upgraded) — DB chỉ giữ
    sha256 hex (worker_token_hash); plaintext trả về worker 1 lần khi claim.
    Migration 2026-10-16_worker_token_hash.sql."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "jobs_status_idx",
            "status",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    # wave-2 #3 (spec 2026-10-14): tên file gốc client khai khi create →
    # GET /jobs q ILIKE. ALTER-only migration (create_all never ALTERs):
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS filename TEXT;
    # Legacy rows NULL → q không khớp (accept).
    status: Mapped[str] = mapped_column(
        Text, default="queued", server_default=text("'queued'")
    )
    storage_key: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer)
    preprocess: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plan D4: export format chosen at upload ("md"|"docx"). Nullable —
    # ALTER-only migration (create_all never ALTERs); readers use
    # `job.output_format or "md"`.
    output_format: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="md"
    )
    # Phase 5 (plan 2026-10-10): "layout" (default) | "extract_only" —
    # extract_only skips auto-gen layout. ALTER-only migration:
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'layout';
    # Readers use `job.mode or "layout"` (legacy NULL rows).
    mode: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="layout"
    )
    # Plan M: word style overrides — JSON object (enum keys, typed values)
    # hoặc NULL. ALTER-only migration (create_all never ALTERs):
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS layout_style TEXT;
    # Readers parse via json.loads (broken JSON → None + warning).
    layout_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 1 (plan 2026-10-10): text-edit counter, optimistic lock for
    # POST /extraction. ALTER-only migration:
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS text_version INT NOT NULL DEFAULT 0;
    text_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # WS-SERVER queue: text save khi rendering / sync targeted-fail →
    # finalize render lại tối đa 1 lần (loop guard 2). ALTER-only migration:
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rerender_requested BOOLEAN DEFAULT false;
    # Readers: run-mutable — không cache qua request.
    rerender_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Wave-5 S1 (spec 2026-10-15): bytes upload thật (refund = 0 khi
    # failed/cancelled) + dấu file gốc đã purge. ALTER-only migration:
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS upload_bytes bigint NOT NULL DEFAULT 0;
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS storage_purged_at timestamptz NULL;
    upload_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    storage_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Job status phases (spec 2026-10-09): queued | extracting | rendering |
    # done | failed ("running" eliminated). ALTER-only migration:
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kaggle_ref TEXT;
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_step TEXT;
    # kaggle_ref persists the batch kernel ref so a restart re-adopts the
    # run; failed_step is the retry target ("extracting" | "rendering").
    kaggle_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    # IR rewrite: LLM-produced Document IR JSON (nullable, ALTER-only)
    ir_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Spec kaggle session worker (2026-10-16, T2): session-scope claim —
    # worker_token_hash giữ nguyên cho HTTP Colab path; session mode gán
    # session_id (worker_token_hash NULL). FK ON DELETE SET NULL (AC3a):
    # close session DELETE hash row → job.session_id tự NULL, job không mất.
    # ALTER-only migration (create_all never ALTERs):
    #   ALTER TABLE jobs ADD COLUMN IF NOT EXISTS session_id BIGINT
    #     REFERENCES worker_sessions(id) ON DELETE SET NULL;
    session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("worker_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class DocumentVersion(Base):
    """Phase 1 (spec Sub-system A): per-(job, kind) snapshot row.

    kind: 'text' | 'md-layout' | 'docx-layout'; storage_key points at the
    S3 snapshot object (versions/{job_id}/{kind}/{version}); N=20 newest
    per (job, kind) kept (service prunes). Hand-applied migration:
      CREATE TABLE document_versions (
        id BIGSERIAL PRIMARY KEY,
        job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        storage_key TEXT NOT NULL,
        version INT NOT NULL,
        based_on_text_version INT NOT NULL DEFAULT 0,
        detached BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (job_id, kind, version)
      );
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "kind", "version", name="uq_dv_job_kind_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    based_on_text_version: Mapped[int] = mapped_column(Integer, default=0)
    detached: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

class OcrSuggestion(Base):
    """Plan proofread: LLM-detected OCR error candidate (user decides).

    start/end = char offsets into the PAGE TEXT (regions joined by \\n) —
    informational only; the client re-locates by `original` (fuzzy) because
    editor content ≠ page text. Dev DB: table created by hand via psql
    (Alembic deferred):
      CREATE TABLE ocr_suggestions (
        id SERIAL PRIMARY KEY,
        job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        page_index INTEGER NOT NULL,
        start INTEGER NOT NULL,
        end INTEGER NOT NULL,
        original TEXT NOT NULL,
        suggestion TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
      );
      CREATE INDEX ix_ocr_suggestions_job_id ON ocr_suggestions (job_id);
    """

    __tablename__ = "ocr_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    page_index: Mapped[int] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    original: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, default="pending", server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

class WorkerHeartbeat(Base):
    """wave-2 #7 (spec 2026-10-14): worker liveness — 1 row/worker_id, upsert.

    kind: "loop" (Colab /next loop, POST /api/worker/heartbeat) |
    "kaggle-batch" (orchestrator marker: upsert khi spawn + mỗi poll status).
    Hand-SQL migration (dev/prod; test tạo qua create_all):
      CREATE TABLE IF NOT EXISTS worker_heartbeats (
        worker_id text PRIMARY KEY,
        kind text,
        last_seen timestamptz NOT NULL,
        current_job_id int null
      );
    """

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

class WorkerSession(Base):
    """Kaggle session loop worker (spec 2026-10-16 T2): 1 row / kernel
    session. key_hash = sha256(session_key) — hash-at-rest (P2 #16 pattern);
    plaintext key trả về worker 1 lần khi claim. closed_at NULL = live —
    close session DELETE row NGAY (AC3/AC9); jobs.session_id FK SET NULL.
    Migration: docs/migrations/2026-10-16_worker_sessions.sql (T1)."""

    __tablename__ = "worker_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kernel_ref: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text)
    spawned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_seconds_reported: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
