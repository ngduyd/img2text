"""App settings, read from environment (env names are case-insensitive)."""

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
    # CORS: comma-separated regex parts, joined with "|" (R58; VSCode
    # port-forward origins bypass the vite dev proxy's same-origin setup).
    allowed_origins: str = r"http://localhost:.*|http://127\.0\.0\.1:.*|.*vscode\.dev"
    # Scheduler claim/reap interval (R58); floor 5s — no busy-loop.
    scheduler_interval_seconds: int = 60

    @field_validator("scheduler_interval_seconds")
    @classmethod
    def _floor_scheduler_interval(cls, v: int) -> int:
        return max(5, v)


settings = Settings()
