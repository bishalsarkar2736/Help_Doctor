import time
import uuid
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.try_except.context import request_id_ctx

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request_id_ctx.set(request_id)

        start_time = time.time()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled exception during request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise

        duration_ms = round((time.time() - start_time) * 1000, 2)

        logger.info(
            "Request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        response.headers["X-Request-ID"] = request_id
        return response
