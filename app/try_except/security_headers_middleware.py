from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Swagger UI / ReDoc load assets from a CDN and use inline scripts, so a strict
# CSP would break them. They're exempted; every other (JSON) response gets the
# lock-everything-down policy below.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

# This API serves JSON only — no resource is ever legitimately loaded from one
# of its responses, so deny everything. frame-ancestors reinforces
# X-Frame-Options for modern browsers.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds baseline security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        # HSTS only over HTTPS. Sending it over plain HTTP is meaningless per
        # RFC 6797, and actively harmful in development: a browser that honors
        # it pins the whole host (+ subdomains, for 2 years) to HTTPS, so
        # http://localhost:8000 then fails to connect and the frontend reports
        # "Cannot reach the server". Honor X-Forwarded-Proto when behind a proxy
        # that terminates TLS.
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        is_https = (
            request.url.scheme == "https"
            or forwarded_proto.split(",")[0].strip() == "https"
        )

        if is_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )

        if not request.url.path.startswith(_DOCS_PATHS):
            response.headers["Content-Security-Policy"] = _API_CSP

        return response
