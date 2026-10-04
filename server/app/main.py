"""FastAPI app factory."""

from fastapi import FastAPI

from app.config import settings
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.include_router(health.router)
    return app
