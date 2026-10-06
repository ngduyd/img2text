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
    # Enabled iff username + key + kernel_ref all set — feature self-disables
    # and the server never imports the kaggle package otherwise.
    kaggle_username: str = ""
    kaggle_key: str = ""
    kaggle_kernel_ref: str = ""  # e.g. "user/img2text-worker"
    kaggle_accelerator: str = "NvidiaTeslaT4"
    # Ceiling note only (P2): kaggle kernels_push has no reliable timeout kw —
    # real session cap = Kaggle platform; our control is the re-push gap guard.
    kaggle_timeout: int = 10800
    kaggle_min_queue: int = 1
    kaggle_min_gap_seconds: int = 600
    kaggle_stage_src: str = "deploy/kaggle"
    kaggle_stage_dir: str = "/tmp/img2text-kaggle-kernel"

    @property
    def kaggle_enabled(self) -> bool:
        return bool(self.kaggle_username and self.kaggle_key and self.kaggle_kernel_ref)

    @field_validator("scheduler_interval_seconds")
    @classmethod
    def _floor_scheduler_interval(cls, v: int) -> int:
        return max(5, v)


settings = Settings()
