"""App settings from environment (case-insensitive env names; pydantic-settings).

Rulings embedded: R58 CORS regex origins incl. VSCode port-forward hosts;
R58a scheduler_interval_seconds floor 5s (no busy-loop).
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test"
    )
    app_secret: str = "dev-secret-change-me"
    base_url: str = "http://localhost:8000"
    admin_email: str = ""
    admin_password: str = ""
    log_path: str = "logs/img2text.log"
    runner_key: str = "dev-runner-key"
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
    kaggle_batch_max_jobs: int = 20
    kaggle_stage_src: str = "deploy/kaggle"
    kaggle_stage_dir: str = "/tmp/img2text-kaggle-kernel"
    # Plan K5: orchestration mode. "batch" (default) = backend drives the
    # standalone script kernel (no public URL needed); "loop" = Plan K2
    # worker kernel polling the backend (needs public BASE_URL + Secrets).
    kaggle_mode: str = "batch"
    # Plan D2: LLM layout plan for the docx-layout export (local
    # OpenAI-compatible server, e.g. llm.cpp at localhost:20128).
    llm_base_url: str = "http://localhost:20128/v1"
    llm_model: str = "oc/muse-spark-1.3-contributor-free"
    llm_timeout: int = 120
    # IR rewrite: LLM phân loại cấu trúc document (config: ir_llm_model)
    ir_llm_model: str = "oc/mimo-v2.6-flash-free"
    # Proofread dùng model riêng (khác layout model) — cùng endpoint.
    proofread_llm_model: str = "oc/longcat-2.5-preview-free"
    # Bearer token for remote /v1/chat/completions; empty = no Authorization
    # header (local servers without auth keep working unchanged).
    llm_api_key: str = ""

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


settings = Settings()
