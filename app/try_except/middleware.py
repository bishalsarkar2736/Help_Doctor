import time
import uuid
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.try_except.context import request_id_ctx
from app.core.metrics import api_request_latency, http_requests_total
from app.core.correlation import (
    correlation_id_ctx,
)
from app.core.tracing import (
    inject_trace_attributes,
)

logger = logging.getLogger("app.request")


def _route_template(request: Request) -> str:
    """The matched route's template, or a single bucket for unmatched paths.

    Returning request.url.path here would be a cardinality bomb: every patient
    id, prescription id and scanner probe becomes its own time series. The
    router sets scope["route"] during call_next, so this is only meaningful
    after the response has been produced.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)

    return template or "<unmatched>"


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
            # Count it before re-raising. An exception that escapes here still
            # becomes a 500 for the caller, and leaving it uncounted is exactly
            # the case the error-rate alert exists to catch — the failures that
            # never reached a response handler.
            http_requests_total.labels(
                method=request.method,
                path=_route_template(request),
                status="500",
            ).inc()

            api_request_latency.observe(time.perf_counter() - start_time)

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

        # record metrics
        api_request_latency.observe(duration)

        http_requests_total.labels(
            method=request.method,
            path=_route_template(request),
            status=str(response.status_code),
        ).inc()

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
