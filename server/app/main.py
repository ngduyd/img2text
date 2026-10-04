"""FastAPI app factory."""

from fastapi import FastAPI

from app.config import Settings
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings()
    app.include_router(health.router)
    return app
