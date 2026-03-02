from fastapi import FastAPI
from contextlib import asynccontextmanager
from starlette.responses import JSONResponse

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.db.postgres import engine

from app.try_except.logging import setup_logging


from app.websocket.routes import router as ws_router

from app.errors.handlers import (
    app_exception_handler,
    unhandled_exception_handler,
)

from app.try_except.exceptions import AppException
from app.try_except.logging import setup_logging
from app.try_except.middleware import RequestLoggingMiddleware



from app.api.routes import (
    admin,
    doctors_router, auth_router,
    doctor_availability_router,
    appointments_router,
    admin_doctors_router,
    notification_router
)



settings = get_settings()

@asynccontextmanager
async def lifespan(app:FastAPI):
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda _:None)
    except Exception as exc:
        raise RuntimeError("Database connective failed") from exc
    
    yield

    #shutdown
    await engine.dispose()
    

def create_app() -> FastAPI:
    setup_logging(settings.DEBUG)
    


    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
        version="1.0.0"
    )

    app.add_middleware(RequestLoggingMiddleware)

    limiter = Limiter(key_func=get_remote_address)
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
            "status" : "ok",
            "app" : settings.APP_NAME,
            "environment": settings.ENV
        }

        
    app.include_router(auth_router)
    app.include_router(doctors_router)
    app.include_router(doctor_availability_router)
    app.include_router(appointments_router)
    app.include_router(admin_doctors_router)
    app.include_router(admin.router)
    app.include_router(ws_router)
    app.include_router(notification_router)
    


    return app


app = create_app()
