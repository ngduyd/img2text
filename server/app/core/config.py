"""App settings from environment (case-insensitive env names; pydantic-settings).

Rulings embedded: R58 CORS regex origins incl. VSCode port-forward hosts;
R58a scheduler_interval_seconds floor 5s (no busy-loop).
"""

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # S5 gating: env=="test" → EmailVerifyGateMiddleware skip (conftest set;
    # test gating bật lại bằng monkeypatch). Deploy/dev giữ default "dev".
    env: str = "dev"
    database_url: str = (
        "postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test"
    )
    # P0 spec 2026-10-15: no insecure default. Empty on construct; non-prod
    # fills dev placeholder (validator below), prod stays empty → lifespan
    # raises RuntimeError (fail-fast: empty, dev default, or <32 chars).
    app_secret: str = ""
    base_url: str = "http://localhost:8000"
    admin_email: str = ""
    admin_password: str = ""
    log_path: str = "logs/img2text.log"
    runner_key: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"
    r2_endpoint: str = ""
    # R2 account id — endpoint auto-built https://{id}.r2.cloudflarestorage.com
    # when R2_ENDPOINT is empty (prod: fill either one; dev keeps explicit
    # localstack R2_ENDPOINT).
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_region: str = "auto"
    # Spec-reserved public CDN domain for crops/exports; no consumer yet.
    r2_public_base: str = ""
    # Public endpoint for presigned file links (fetched by the USER'S BROWSER,
    # e.g. http://localhost:4566 in dev). Empty = ops endpoint (prod R2
    # unchanged — single-endpoint behavior).
    storage_public_endpoint: str = ""
    # CORS: comma-separated regex parts, joined with "|" (R58; VSCode
    # port-forward origins bypass the vite dev proxy's same-origin setup).
    allowed_origins: str = (
        r"http://localhost:.*|http://127\.0\.0\.1:.*|https://[a-z0-9-]+\.vscode\.dev"
    )
    # Scheduler claim/reap interval (R58); floor 5s — no busy-loop.
    scheduler_interval_seconds: int = 60
    # Wave-5 S1: purge file gốc — interval tick (floor 60s) + retention 7d.
    purge_interval_seconds: int = 3600
    purge_retention_days: int = 7
    # P2 #19 (spec 2026-10-16): presigned URL expiry windows — crop artifact
    # 1h (serve-time re-presign mỗi lần, không cache); input_url 15 phút
    # (kernel fetch ngay sau spawn tick). Window ngắn = giảm stale-link
    # trong artifact + giảm exposure URL presigned.
    crop_presign_expires: int = 3600
    input_url_expires: int = 900
    # Plan K2: Kaggle worker orchestration (backend auto-spawn kernel run).
    # Enabled iff username + (key OR api_token) + kernel_ref all set — feature
    # self-disables and the server never imports the kaggle package otherwise.
    kaggle_username: str = ""
    kaggle_key: str = ""
    # kaggle 2.x primary auth (Bearer KGAT_): kaggle's authenticate() reads
    # env KAGGLE_API_TOKEN directly; config == process env (compose passes it
    # through), so no credential wiring in the orchestrator. Empty → legacy key.
    kaggle_api_token: str = ""
    kaggle_kernel_ref: str = ""  # e.g. "user/img2text-worker"
    kaggle_accelerator: str = "NvidiaTeslaT4"
    # Ceiling note only (P2): kaggle kernels_push has no reliable timeout kw —
    # real session cap = Kaggle platform; our control is the re-push gap guard.
    kaggle_timeout: int = 10800
    kaggle_min_queue: int = 1
    kaggle_min_gap_seconds: int = 600
    # Batch one-run (spec 2026-10-09): max queued jobs staged into ONE kernel
    # run (env KAGGLE_BATCH_MAX_JOBS; extra jobs wait for the next tick).
    # 0 hoặc -1 = unlimited — gom hết queued trong một run.
    kaggle_batch_max_jobs: int = 20
    # P2-5: unified page cap — MỘT config cho presign/create (server);
    # default = kernel hard cap (deploy/kaggle MAX_PDF_PAGES=100). Web upload
    # UI cap (25) thuộc lane web — server chỉ expose config này.
    max_pages: int = 100
    kaggle_stage_src: str = "deploy/kaggle"
    kaggle_stage_dir: str = "/tmp/img2text-kaggle-kernel"
    # Plan K5: orchestration mode. "batch" (default) = backend drives the
    # standalone script kernel (no public URL needed); "loop" = Plan K2
    # worker kernel polling the backend (needs public BASE_URL + Secrets).
    kaggle_mode: str = "batch"
    # Plan D2: LLM layout plan for the docx-layout export (local
    # OpenAI-compatible server, e.g. llm.cpp at localhost:20128). Empty
    # default (P0 spec 2026-10-15): prod fail-fast when kaggle (LLM) feature
    # enabled; dev value lives in deploy/.env.dev.
    llm_base_url: str = ""
    llm_model: str = "oc/muse-spark-1.3-contributor-free"
    # LLM request timeout (seconds)
    llm_timeout: int = Field(
        default=180, description="LLM request timeout (seconds)"
    )  # LLM free chậm — 180s (2 retry → worst ~6 phút/call)
    # IR rewrite: LLM phân loại cấu trúc document (config: ir_llm_model)
    ir_llm_model: str = "oc/mimo-v2.6-flash-free"
    # Proofread dùng model riêng (khác layout model) — cùng endpoint.
    proofread_llm_model: str = "oc/longcat-2.5-preview-free"
    # Bearer token for remote /v1/chat/completions; None = no Authorization
    # header (local servers without auth keep working unchanged).
    llm_api_key: str | None = Field(
        default=None, description="LLM API key (masked write-only)"
    )

    @property
    def r2_endpoint_url(self) -> str:
        """Effective storage endpoint: explicit R2_ENDPOINT wins; else build
        from R2_ACCOUNT_ID; else empty (default AWS endpoint)."""
        if self.r2_endpoint:
            return self.r2_endpoint
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return ""

    @property
    def kaggle_enabled(self) -> bool:
        # kaggle 2.x: token replaces the legacy key; username stays required
        # (OWNER id in metadata) + kernel_ref (the kernel to spawn).
        return bool(
            self.kaggle_username
            and (self.kaggle_key or self.kaggle_api_token)
            and self.kaggle_kernel_ref
        )

    @field_validator("scheduler_interval_seconds")
    @classmethod
    def _floor_scheduler_interval(cls, v: int) -> int:
        return max(5, v)

    @field_validator("kaggle_mode")
    @classmethod
    def _kaggle_mode_values(cls, v: str) -> str:
        if v not in ("batch", "loop"):
            raise ValueError("kaggle_mode phải là batch hoặc loop")
        return v

    @model_validator(mode="after")
    def _dev_placeholder_secrets(self) -> "Settings":
        """Dev/test keep placeholder secrets; prod (env=="prod") keeps whatever
        was set — empty survives to lifespan fail-fast."""
        if self.env != "prod":
            if not self.app_secret:
                self.app_secret = "dev-secret-change-me"
            if not self.runner_key:
                self.runner_key = "dev-runner-key"
        return self

    @field_validator("llm_api_key")
    @classmethod
    def _empty_llm_key_is_none(cls, v: str | None) -> str | None:
        """LLM_API_KEY= (rỗng trong env) → None, không giữ "" (falsy cả hai nhưng
        contract test `is None` + consumers check `if api_key` cần nhất quán)."""
        return v or None


settings = Settings()
