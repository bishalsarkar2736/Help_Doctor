import os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from contextlib import asynccontextmanager,suppress
from starlette.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.db.postgres import engine
from app.core.limiter import limiter


from app.websocket.routes import router as ws_router

from app.errors.handlers import (
    app_exception_handler,
    unhandled_exception_handler,
)

from app.try_except.exceptions import AppException
from app.try_except.logging import setup_logging
from app.try_except.middleware import RequestLoggingMiddleware

from app.try_except.correlation_middleware import CorrelationIdMiddleware
from app.try_except.security_headers_middleware import SecurityHeadersMiddleware
from app.try_except.trusted_host_middleware import TrustedHostMiddleware
from app.websocket.redis_listener import redis_listener

import asyncio

from fastapi.middleware.cors import CORSMiddleware

from app.core.tracing import setup_tracing
from app.core.sentry import setup_sentry

from prometheus_client import (
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi.responses import Response
from app.api.routes import (
    ALL_ROUTERS,
)
from app.services.health_service import HealthService

import logging

logger = logging.getLogger(__name__)


settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):

    redis_task = None

    if os.getenv("TESTING") != "1":

        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda _: None)

        except Exception:
            logger.exception(
                "Database startup failed"
            )
            raise

        redis_task = asyncio.create_task(
            redis_listener()
        )

    try:
        yield

    finally:

        if redis_task:
            redis_task.cancel()

            with suppress(asyncio.CancelledError):
                await redis_task

        if os.getenv("TESTING") != "1":
            await engine.dispose()
    

def create_app() -> FastAPI:
    setup_logging(settings.DEBUG)
    setup_sentry()


    Path("media/signatures").mkdir(
        parents=True,
        exist_ok=True,
    )

    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
        version="1.0.0"
    )

    # /media and /uploads are served by app/api/routes/files.py, through the
    # storage seam, so the same URLs work whether files live on disk or in
    # object storage. A StaticFiles mount reads the local directory directly
    # and would silently serve nothing under STORAGE_BACKEND=s3 — every doctor
    # signature in the UI would become a broken image.

    setup_tracing(app)

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # Added LAST so it runs FIRST — Starlette applies middleware in reverse
    # order of registration. A forged Host is rejected before it is written to
    # the request log, before it can spend rate-limit budget, and before
    # anything downstream builds a URL or resolves a tenant from it.
    app.add_middleware(TrustedHostMiddleware)


    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request, exc):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Try again later."},
        )



    @app.get(
    "/health/live",
    tags=["Health"],
    )
    async def liveness_check():

        return {
            "status": "alive",
            "app": settings.APP_NAME,
        }
    

    @app.get(
    "/health/ready",
    tags=["Health"],
    )
    async def readiness_check():

        database, redis = await asyncio.gather(
            HealthService.check_database(),
            HealthService.check_redis(),
        )

        ready = (
            database["status"] == "healthy"
            and redis["status"] == "healthy"
        )

        return {
            "status": (
                "ready"
                if ready
                else "not_ready"
            ),
            "services": {
                "database": database,
                "redis": redis,
            },
        }
        

    @app.get(
    "/health",
    tags=["Health"],
    )
    async def health_check():

        database, redis = await asyncio.gather(
            HealthService.check_database(),
            HealthService.check_redis(),
        )

        services = {
            "database": database,
            "redis": redis,
        }

        overall_status = "healthy"

        if (
            database["status"] == "unhealthy"
            or redis["status"] == "unhealthy"
        ):
            overall_status = "unhealthy"

        return {
            "status": overall_status,
            "app": settings.APP_NAME,
            "environment": settings.ENV,
            "version": "1.0.0",
            "services": services,
        }
    


    @app.get("/metrics")
    async def metrics(
        authorization: str | None = Header(default=None),
    ):
        if settings.METRICS_TOKEN:
            if authorization != f"Bearer {settings.METRICS_TOKEN}":
                raise HTTPException(status_code=401, detail="Unauthorized")

        elif settings.ENV == "production":
            raise HTTPException(status_code=404)

        return Response(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )


    for router in ALL_ROUTERS:
        app.include_router(router)

    app.include_router(ws_router)

    return app


app = create_app()
