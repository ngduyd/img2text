"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.admin import bootstrap_admin
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.middleware import PageViewsMiddleware, RequestLogsMiddleware
from app.routers import admin, auth, health
from app.scheduler import init_scheduler
from app.storage import build_storage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ponytail: single create_all until schema stabilizes; upgrade to
    # Alembic before first deploy (Plan B adds jobs table).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await bootstrap_admin(session, settings.admin_email, settings.admin_password)
    init_scheduler(app)
    yield
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    # Ruling R6: pure-ASGI logging middlewares open their own sessions here
    app.state.session_factory = SessionLocal
    app.state.storage = build_storage()
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    # Starlette add_middleware inserts at head → last added = outermost
    app.add_middleware(PageViewsMiddleware)
    app.add_middleware(RequestLogsMiddleware)
    return app
