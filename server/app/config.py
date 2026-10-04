"""App settings, read from environment (env names are case-insensitive)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test"
    )
    app_secret: str = "dev-secret-change-me"
    base_url: str = "http://localhost:8000"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me"
    log_path: str = "logs/img2text.log"
    runner_key: str = "dev-runner-key"
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "noreply@example.com"
