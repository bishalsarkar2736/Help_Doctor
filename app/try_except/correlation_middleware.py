import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.try_except.context import request_id_ctx


class CorrelationIdMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        request_id = request.headers.get("X-Request-ID")

        if not request_id:
            request_id = str(uuid.uuid4())

        request_id_ctx.set(request_id)

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id

        return response