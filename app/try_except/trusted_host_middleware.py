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

One path is exempt -- /metrics, scraped internally by Prometheus under a Host it
cannot override. See METRICS_PATH below for why that is safe there and nowhere
else.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings
from app.domain.clinics.subdomain import subdomain_from_host


# The one path the allowlist does not apply to.
#
# Prometheus scrapes this over the internal network as `api:8000`, and the Host
# header it sends is derived from the target address -- Prometheus has no option
# to override it. So the scrape arrived as `Host: api`, which is not a hostname
# this deployment serves, and every scrape was answered 400. The `fastapi` target
# had been DOWN for as long as it had existed, which meant every alert built on
# API metrics -- error rates, latency, "no traffic received" -- had no data
# behind it and could never fire.
#
# Exempting a path rather than accepting the hostname, because the two differ in
# blast radius. Accepting `api` would accept it EVERYWHERE: nginx matches
# `server_name _` and forwards any client-supplied Host verbatim, so an external
# caller could send it to the password-reset route, where the value is built into
# an absolute URL. This exemption reaches one endpoint instead.
#
# It is safe for that endpoint specifically, because the reason this middleware
# exists does not apply to it. Nothing in /metrics reads the Host header: it
# renders a static exposition of counters and builds no URL, no cache key and no
# tenant. And it is not unauthenticated -- it requires `Bearer $METRICS_TOKEN`
# when that is set, and 404s outright when ENV=production and it is not.
METRICS_PATH = "/metrics"


def _host_is_served(host: str, settings) -> bool:
    """Whether this deployment answers on `host`.

    Two rules, in this order, and the second is deliberately narrow.

    LITERAL: equality against allowed_hosts_list, exactly as before. Every host
    that worked before this function existed still takes this path.

    WILDCARD: for each configured `*.base`, the host is accepted only if it is
    `<label>.base` where `<label>` is a subdomain this platform would have
    issued. That test is subdomain_from_host, the SAME function the tenant
    resolver uses — so the allowlist cannot drift from what routing accepts,
    and all of its refusals are inherited for free:

      - exactly one label, so `a.b.example.com` is refused
      - RFC 1123 format, so `-bad.example.com` is refused
      - the reserved list, so `api.example.com` and `www.example.com` are
        refused even though they fit the pattern
      - the apex itself returns None, so `example.com` is NOT covered by
        `*.example.com` and needs its own literal entry

    A suffix test alone would not do: `evil-example.com` and
    `example.com.evil.com` both end in something that looks like the base, and
    subdomain_from_host rejects each because it requires the separating dot and
    the exact remainder.
    """
    if host in settings.allowed_hosts_list:
        return True

    for base in settings.allowed_host_suffixes:
        if subdomain_from_host(host, base) is not None:
            return True

    return False


class TrustedHostMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        # Compared exactly, not by prefix: a `startswith` would also exempt
        # /metrics-something, and the exemption should reach precisely the route
        # it was reasoned about.
        if request.url.path == METRICS_PATH:
            return await call_next(request)

        settings = get_settings()

        # The port is not part of the identity being checked: the same host
        # reached on :8000 in development and :443 in production is the same
        # host, and the allowlist is written without ports.
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()

        # X-Forwarded-Host is deliberately NOT consulted. nginx sets it from
        # the same client-supplied value, so honouring it would add a second
        # spoofable channel that reaches the same decision.

        if host and not _host_is_served(host, settings):
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
