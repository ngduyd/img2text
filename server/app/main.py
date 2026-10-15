"""FastAPI app factory: lifespan + wiring.

Lifespan: create_all → admin bootstrap → scheduler; shutdown closes the
scheduler and engine. Ruling R6: pure-ASGI middlewares read
app.state.session_factory (set here). Routers mount order: auth, profile
(same /api/auth prefix), admin, jobs, exports, region_edit.
"""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.admin_bootstrap import bootstrap_admin
from app.services.email_sends import EmailLimitExceeded
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.core.ratelimit import RateLimitMiddleware
from app.core.middleware import (
    EmailVerifyGateMiddleware,
    PageViewsMiddleware,
    RequestLogsMiddleware,
)
from app.routers import admin, auth, exports, feedback, health, jobs, profile, region_edit
from app.services.scheduler import init_scheduler
from app.services.storage import build_storage


def _validate_prod_config() -> None:
    """P0 spec 2026-10-15: prod boots only with real secrets + LLM endpoint
    when LLM features are on (single gate at startup; dev/test skip)."""
    if settings.env != "prod":
        return
    if (
        not settings.app_secret
        or settings.app_secret == "dev-secret-change-me"
        or len(settings.app_secret) < 32
    ):
        raise RuntimeError(
            "prod requires app_secret: set APP_SECRET (32+ chars, not dev default)"
        )
    if not settings.runner_key or settings.runner_key == "dev-runner-key":
        raise RuntimeError(
            "prod requires runner_key: set RUNNER_KEY (not dev default)"
        )
    # LLM features = kaggle orchestration enabled (spec test; future LLM
    # feature flags join this check).
    if settings.kaggle_enabled and not settings.llm_base_url:
        raise RuntimeError("prod requires LLM_BASE_URL when LLM features enabled")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # P0 fail-fast: reject bad prod config BEFORE touching the DB.
    _validate_prod_config()
    # optional dep: HEIC/HEIF decode cho pipeline; thiếu → warning, heic
    # upload sẽ fail ở rasterize thay vì fail boot.
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        logging.getLogger(__name__).warning(
            "pillow-heif không cài — HEIC/HEIF không decode được"
        )
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
    # S5: 429 flat body {code:"email_limit", retry_after_seconds} (không bọc detail)
    @app.exception_handler(EmailLimitExceeded)
    async def _email_limit_handler(request, exc):
        return JSONResponse(
            status_code=429,
            content={
                "code": "email_limit",
                "retry_after_seconds": exc.retry_after_seconds,
            },
        )
    # Ruling R6: pure-ASGI logging middlewares open their own sessions here
    app.state.session_factory = SessionLocal
    app.state.storage = build_storage()
    app.include_router(health.router)
    app.include_router(auth.router)
    # profile after auth (same /api/auth prefix; PATCH /profile)
    app.include_router(profile.router)
    app.include_router(admin.router)
    app.include_router(jobs.router)
    app.include_router(exports.router)
    app.include_router(region_edit.router)
    # wave-5 S6: POST /api/feedback + GET /api/admin/feedbacks
    app.include_router(feedback.router)
    # Starlette add_middleware inserts at head → last added = outermost.
    # Rate limit innermost (thêm trước cùng) → 429 vẫn đi qua CORS/logging
    # header trước khi về client.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(PageViewsMiddleware)
    app.add_middleware(RequestLogsMiddleware)
    # S5: gate email-verify — innermost OK (403 xẩy ra trước routing deps)
    app.add_middleware(EmailVerifyGateMiddleware)
    # R58 CORS: prod nginx serves same-origin; regex covers localhost/127.0.0.1
    # ports and VSCode forwarded origins. allow_methods: full safe set —
    # Starlette's GET-only default would 400 the POST /jobs preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=re.compile(
            "|".join(
                p.strip() for p in settings.allowed_origins.split(",") if p.strip()
            )
        ),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        # R58a review: explicit echo for credentialed JSON/API preflights
        allow_headers=["Authorization", "Content-Type"],
    )
    return app

# uvicorn entrypoint (dev + deploy/Dockerfile CMD: uvicorn app.main:app)
app = create_app()
