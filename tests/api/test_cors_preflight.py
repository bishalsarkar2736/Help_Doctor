"""CORS preflight must succeed, with tracing instrumentation active.

A browser sends OPTIONS before any cross-origin request that carries an
Authorization header. If that preflight fails, the SPA cannot make a single
authenticated call — even though curl (which sends no preflight) and the rest of
this suite (which runs with tracing disabled) both look perfectly healthy.

That is exactly how a 500 on every preflight shipped unnoticed: an OpenTelemetry
version that predated FastAPI's `_IncludedRouter` read `.path` off it and raised
AttributeError. Fixed by upgrading opentelemetry-instrumentation-* to 0.65b0,
whose `_flatten_routes` resolves those nodes.

These tests assert the *behaviour* rather than the mechanism, so they hold
whether the cause is a dependency version, middleware order, or config —
and they will fail if the OTel pins are ever rolled back.
"""

import pytest

ORIGIN = "http://localhost:5173"


@pytest.mark.asyncio
async def test_preflight_on_authenticated_route_succeeds(client):
    response = await client.options(
        "/users/me",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code < 400, response.text
    assert response.headers.get("access-control-allow-origin") == ORIGIN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/users/me",
        "/appointments/own",
        "/doctors",
        "/admin/users",
        "/prescriptions/1/pdf",
    ],
)
async def test_preflight_succeeds_across_route_shapes(client, path):
    """Includes nested/included routers, which is where the bug lived."""

    response = await client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code < 400, f"{path}: {response.text}"
