import os
from pathlib import Path
from fastapi import FastAPI
from contextlib import asynccontextmanager,suppress
from starlette.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.db.postgres import engine
from app.core.limiter import limiter

from fastapi.staticfiles import StaticFiles

from app.websocket.routes import router as ws_router

from app.errors.handlers import (
    app_exception_handler,
    unhandled_exception_handler,
)

from app.try_except.exceptions import AppException
from app.try_except.logging import setup_logging
from app.try_except.middleware import RequestLoggingMiddleware

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.try_except.correlation_middleware import CorrelationIdMiddleware
from app.task.appointment_reminders import send_appointment_reminders
from app.websocket.redis_listener import redis_listener

import asyncio

from fastapi.middleware.cors import CORSMiddleware

from app.core.tracing import setup_tracing

from prometheus_client import (
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi.responses import Response

from app.api.routes import (
    admin_router,
    doctors_router,
    auth_router,
    doctor_availability_router,
    appointments_router,
    admin_doctors_router,
    notification_router,
    patients_router,
    users_router,
    metric_router,
    prescription_router,
    payment_router,
    slot_router,
    admin_analytics_router,
    push_router,
    notification_preferences_router,
    medicine_api_router,
    admin_medicine_router,
    admin_medicine_analytics_router,
    admin_medicine_alias_api_router,
    admin_medicine_ai_router,
    admin_medicine_ai_logs_router,
    admin_medicine_ai_analytics_router,
    admin_medicine_ai_feedback_router,
    admin_clinic_router,
    admin_clinic_analytics_router,
    admin_revenue_analytics_router,
    admin_dashboard_router,
    admin_clinic_logo_router,
)

import logging

logger = logging.getLogger(__name__)


settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):

    print("TESTING =", os.getenv("TESTING"))

    scheduler = None
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

        scheduler = AsyncIOScheduler()

        scheduler.add_job(
            send_appointment_reminders,
            trigger="interval",
            minutes=1,
            max_instances=1,
        )

        scheduler.start()

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

        if scheduler:
            scheduler.shutdown()

        if os.getenv("TESTING") != "1":
            await engine.dispose()
    

def create_app() -> FastAPI:
    setup_logging(settings.DEBUG)
    

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

    app.mount(
        "/media",
        StaticFiles(directory="media"),
        name="media",
    )

    setup_tracing(app)

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # frontend URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)


    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request, exc):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Try again later."},
        )

    @app.get('/health', tags=["Health"])
    async def health_check():

        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "environment": settings.ENV,
            "version": 1,
            "services": {
                "postgres": "up",
                "redis": "up",
                "websocket": "up",
                "outbox_worker": "up",
            },
        }
    
    @app.get("/metrics")
    async def metrics():

        return Response(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    app.include_router(admin_router)   
    app.include_router(auth_router)
    app.include_router(patients_router)
    app.include_router(users_router)
    app.include_router(doctors_router)
    app.include_router(doctor_availability_router)
    app.include_router(slot_router)
    app.include_router(appointments_router)
    app.include_router(prescription_router)
    app.include_router(medicine_api_router)
    app.include_router(admin_medicine_router)
    app.include_router(admin_medicine_analytics_router)
    app.include_router(admin_medicine_alias_api_router)
    app.include_router(admin_medicine_ai_router)
    app.include_router(admin_medicine_ai_logs_router)
    app.include_router(admin_medicine_ai_analytics_router)
    app.include_router(admin_medicine_ai_feedback_router)
    app.include_router(admin_clinic_logo_router)
    app.include_router(admin_clinic_router)
    app.include_router(admin_clinic_analytics_router)
    app.include_router(admin_revenue_analytics_router)
    app.include_router(admin_dashboard_router)
    app.include_router(admin_doctors_router)
    app.include_router(ws_router)
    app.include_router(notification_router)
    app.include_router(notification_preferences_router)
    app.include_router(metric_router)
    app.include_router(payment_router)
    app.include_router(admin_analytics_router)
    app.include_router(push_router)


    return app


app = create_app()
