"""Reject requests carrying a Host header this deployment does not serve.

The Host header is supplied by the client. nginx listens on `server_name _`,
which matches anything, and forwards the value verbatim
(`proxy_set_header Host $http_host`), so whatever a caller writes there arrives
intact. Anything downstream that trusts it inherits that: absolute URLs built
for emails and password resets, cache keys, and — once it exists — resolving
which tenant a request belongs to.

Checked here rather than in nginx because this is where it holds in every
environment. nginx cannot name the real hostnames until DNS and TLS exist, and
a check that is only present in production is a check that has never run.

Starlette ships TrustedHostMiddleware, which does the same comparison but
answers with a plain-text 400 that bypasses the application's error envelope.
Every other rejection this API makes is {"error": {"type", "message"}}, and a
client parsing that would see this one as a transport failure instead.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings


class TrustedHostMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # The port is not part of the identity being checked: the same host
        # reached on :8000 in development and :443 in production is the same
        # host, and the allowlist is written without ports.
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()

        # X-Forwarded-Host is deliberately NOT consulted. nginx sets it from
        # the same client-supplied value, so honouring it would add a second
        # spoofable channel that reaches the same decision.

        if host and host not in settings.allowed_hosts_list:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "type": "InvalidHost",
                        # The rejected value is echoed because the common cause
                        # is a misconfigured proxy rather than an attack, and
                        # the header is already client-supplied — repeating it
                        # discloses nothing the caller did not send.
                        "message": f"Host {host!r} is not served by this deployment",
                    }
                },
            )

        return await call_next(request)
