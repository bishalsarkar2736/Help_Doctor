"""/health/ready has to answer in the status line, not only in the body.

WHAT WAS WRONG
The route returned a plain dict, so FastAPI sent HTTP 200 whatever the checks
found. With Postgres unreachable it answered

    HTTP 200  {"status": "not_ready", ...}

which is a readiness probe that says "not ready" and "fine" in the same breath.
Everything downstream reads the status line, not the body: a load balancer
deciding whether to route to this instance, an orchestrator deciding whether a
rollout succeeded, and scripts/staging.sh's wait_for_health, which polls for a
200 and would have declared a database-less API ready.

WHAT THESE TESTS PIN
The status code for every combination of dependency health, that the body is
unchanged so existing consumers keep working, and that /health/live is
untouched — liveness answers a different question ("is the process up?") and
must not start failing because a dependency is down, or an orchestrator would
restart a healthy process it cannot fix by restarting.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.health_service import HealthService

READY = "/health/ready"
LIVE = "/health/live"

UNHEALTHY = {
    "status": "unhealthy",
    "error": "connection refused",
    "checked_at": "2026-01-01T00:00:00+00:00",
}

HEALTHY = {
    "status": "healthy",
    "checked_at": "2026-01-01T00:00:00+00:00",
}


def _check(database: dict, redis: dict):
    """Pin both dependency checks to a given result.

    BOTH are stubbed, including the healthy cases, and that is deliberate. What
    is under test here is the ROUTE — does it map a pair of check results onto
    the right status code — not whether Postgres happens to be reachable.

    Letting the real check run also made these tests order-dependent. The app's
    engine caches asyncpg connections against the event loop that created them,
    pytest-asyncio gives each test a fresh loop, and a later test reusing a
    pooled connection fails with "attached to a different loop". That produced a
    503 from a perfectly healthy database, and under random test ordering it
    would surface as an intermittent failure in whichever test happened to run
    second.

    AsyncMock rather than a plain return_value: the route awaits both checks
    through asyncio.gather, and a MagicMock returning a dict is not awaitable.
    """
    return (
        patch.object(
            HealthService, "check_database", new=AsyncMock(return_value=database)
        ),
        patch.object(
            HealthService, "check_redis", new=AsyncMock(return_value=redis)
        ),
    )


def _both_healthy():
    return _check(HEALTHY, HEALTHY)


def _database_down():
    return _check(UNHEALTHY, HEALTHY)


def _redis_down():
    return _check(HEALTHY, UNHEALTHY)


def _both_down():
    return _check(UNHEALTHY, UNHEALTHY)


# ---------------------------------------------------------------------------
# The status line
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthy_dependencies_return_200(client):
    db, redis = _both_healthy()
    with db, redis:
        response = await client.get(READY)

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_an_unhealthy_database_returns_503(client):
    db, redis = _database_down()
    with db, redis:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_an_unhealthy_redis_returns_503(client):
    """Redis alone is enough. The API cannot serve correctly without it —
    sessions, rate limiting and the notification cooldown all depend on it."""
    db, redis = _redis_down()
    with db, redis:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_both_dependencies_unhealthy_returns_503(client):
    db, redis = _both_down()
    with db, redis:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# The body did not change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_healthy_body_keeps_its_shape(client):
    """Anything already parsing this response must keep working — the change is
    to the status line only."""
    db, redis = _both_healthy()
    with db, redis:
        body = (await client.get(READY)).json()

    assert set(body) == {"status", "services"}
    assert set(body["services"]) == {"database", "redis"}
    assert body["services"]["database"]["status"] == "healthy"
    assert body["services"]["redis"]["status"] == "healthy"
    assert "checked_at" in body["services"]["database"]


@pytest.mark.asyncio
async def test_the_failing_body_still_reports_which_dependency_failed(client):
    """The diagnosis has to survive the new status code: a 503 that does not say
    WHICH dependency is down is a worse probe than the one being replaced."""
    db, redis = _database_down()
    with db, redis:
        body = (await client.get(READY)).json()

    assert set(body) == {"status", "services"}
    assert body["services"]["database"]["status"] == "unhealthy"
    assert body["services"]["database"]["error"] == "connection refused"

    # And the one that is still fine is still reported as fine.
    assert body["services"]["redis"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# Liveness is a different question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_liveness_returns_200(client):
    response = await client.get(LIVE)

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_liveness_stays_200_when_dependencies_are_down(client):
    """Deliberately unaffected. Liveness asks whether the process is running;
    restarting it does not fix an unreachable database, so a liveness probe that
    fails on a dependency outage turns one outage into a restart loop.

    This is also the guard against "fixing" readiness by making both endpoints
    check the same things.
    """
    db, redis = _both_down()
    with db, redis:
        response = await client.get(LIVE)

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# The probe is usable as a probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_wait_for_ready_loop_would_not_be_fooled(client):
    """The concrete consumer: scripts/staging.sh polls until the status code is
    200. Before this change that loop passed instantly against an API with no
    database."""
    db, redis = _database_down()
    with db, redis:
        assert (await client.get(READY)).status_code != 200

    db, redis = _both_healthy()
    with db, redis:
        assert (await client.get(READY)).status_code == 200
