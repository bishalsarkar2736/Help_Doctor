import time
import uuid
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.try_except.context import request_id_ctx
from app.core.metrics import api_request_latency
from app.core.correlation import (
    correlation_id_ctx,
)
from app.core.tracing import (
    inject_trace_attributes,
)

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request_id_ctx.set(request_id)
        correlation_id_ctx.set(request_id)
        

        start_time = time.perf_counter()

        try:
            response = await call_next(request)

            inject_trace_attributes()
            
        except Exception:
            logger.exception(
                "Unhandled exception during request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise

        duration = time.perf_counter() - start_time
        duration_ms = round(duration * 1000, 2)

        # record metric
        api_request_latency.observe(duration)

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
