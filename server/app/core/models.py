"""SQLAlchemy ORM models (Task 2): users, tokens, jobs, analytics, settings.

Spec §4 shapes: Job carries storage_key/file_type/page_count/preprocess/
result; worker_token plaintext per ruling R11 (hash-at-rest rides Alembic).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
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


class PasswordResetToken(Base):
    """Single-use password-reset token; DB stores sha256(raw) only (ruling R2)."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    ponytail: worker_token stored plaintext per ruling R11 (single-job
    capability token); hash-at-rest upgrade rides the Alembic pass."""

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
    status: Mapped[str] = mapped_column(
        Text, default="queued", server_default=text("'queued'")
    )
    storage_key: Mapped[str] = mapped_column(Text)
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
    worker_token: Mapped[str | None] = mapped_column(Text, nullable=True)
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
