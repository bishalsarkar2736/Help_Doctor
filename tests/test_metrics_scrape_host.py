"""Prometheus can scrape /metrics, and nothing else got easier to reach.

THE FAILURE
Prometheus scrapes the API over the compose network as `api:8000`, and derives
the Host header from that target address -- there is no scrape option to override
it. `api` is not a hostname this deployment serves, so TrustedHostMiddleware
answered 400 and the `fastapi` target had been DOWN for as long as it existed.
Every alert built on API metrics -- error rates, latency, "no traffic received"
-- had no data behind it and could never have fired.

WHY A PATH EXEMPTION AND NOT AN EXTRA ALLOWED HOST
Accepting `api` as a hostname would accept it EVERYWHERE. nginx matches
`server_name _` and forwards any client-supplied Host verbatim, so an external
caller could send `Host: api` to the password-reset route, where the value is
built into an absolute URL. The exemption reaches one endpoint instead of every
one.

It is safe for that endpoint because the reason the middleware exists does not
apply to it: /metrics reads no Host, builds no URL, no cache key and no tenant,
and it is separately authenticated -- `Bearer $METRICS_TOKEN` when set, 404 when
ENV=production and it is not.

These tests hold both halves at once: the scrape works, and the boundary did not
move for anything else.
"""

import pathlib

import pytest

from app.config import get_settings
from app.try_except.trusted_host_middleware import METRICS_PATH

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent
PROMETHEUS = REPO / "prometheus.yml"

# What Prometheus actually sends, taken from the scrape target rather than
# invented: the Host header follows __address__.
SCRAPE_HOST = "api:8000"

REJECTED_HOSTS = [
    "api:8000",
    "evil.example.com",
    "attacker.test",
    "api.evil.com",
]


# ---------------------------------------------------------------------------
# The scrape works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prometheus_can_scrape_metrics(client):
    """The exact request Prometheus makes."""
    response = await client.get("/metrics", headers={"Host": SCRAPE_HOST})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_the_scrape_returns_actual_metrics(client):
    """A 200 carrying nothing would be just as broken."""
    response = await client.get("/metrics", headers={"Host": SCRAPE_HOST})

    body = response.text

    assert "# HELP" in body
    assert "# TYPE" in body
    assert "python_info" in body or "process_start_time_seconds" in body


@pytest.mark.asyncio
@pytest.mark.parametrize("host", REJECTED_HOSTS + ["localhost", "127.0.0.1"])
async def test_metrics_answers_whatever_host_it_is_asked_with(client, host):
    """The exemption is unconditional for this path, by design: Prometheus's Host
    depends on how the target is addressed, and pinning the allowed value would
    re-break the scrape the first time someone renames the service."""
    response = await client.get("/metrics", headers={"Host": host})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# The boundary did not move
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("host", REJECTED_HOSTS)
async def test_untrusted_hosts_are_still_rejected(client, host):
    """Including `api:8000` itself. The scrape host is accepted on the metrics
    path and nowhere else."""
    response = await client.get("/health/live", headers={"Host": host})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "InvalidHost"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/health/live", "/health/ready", "/api/auth/login", "/docs"]
)
async def test_the_scrape_host_opens_no_other_door(client, path):
    """The whole point of preferring a path exemption to an allowed hostname."""
    response = await client.get(path, headers={"Host": SCRAPE_HOST})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_trusted_hosts_still_work(client):
    """The middleware's ordinary behaviour is untouched."""
    for host in ("localhost", "127.0.0.1"):
        assert (
            await client.get("/health/live", headers={"Host": host})
        ).status_code == 200


@pytest.mark.asyncio
async def test_health_endpoints_are_unchanged(client):
    """Neither liveness nor readiness moved: both still validated, both still
    answering as they did."""
    live = await client.get("/health/live", headers={"Host": "localhost"})

    assert live.status_code == 200
    assert live.json()["status"] == "alive"

    ready = await client.get("/health/ready", headers={"Host": "localhost"})

    assert ready.status_code in (200, 503)
    assert ready.json()["status"] in ("ready", "not_ready")


# ---------------------------------------------------------------------------
# The exemption is exactly one path
# ---------------------------------------------------------------------------


def test_the_exemption_is_a_single_exact_path():
    assert METRICS_PATH == "/metrics"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/metrics/", "/metrics-internal", "/metricsx", "/api/metrics"]
)
async def test_lookalike_paths_are_not_exempt(client, path):
    """Matched exactly rather than by prefix, so `/metrics-anything` cannot
    inherit the exemption by being named carefully."""
    response = await client.get(path, headers={"Host": "evil.example.com"})

    assert response.status_code == 400, (
        f"{path} inherited the /metrics exemption"
    )


def test_host_validation_is_not_a_wildcard():
    """No `*` anywhere in the allowlist, in any environment."""
    hosts = get_settings().allowed_hosts_list

    assert "*" not in hosts
    assert not any("*" in host for host in hosts)
    assert hosts, "the allowlist is empty, which accepts nothing or everything"


def test_the_middleware_still_checks_every_other_request():
    """Structural: the exemption must be a narrow early return, not a disabled
    check."""
    import ast

    from app.try_except import trusted_host_middleware

    source = pathlib.Path(trusted_host_middleware.__file__).read_text()
    tree = ast.parse(source)

    dispatch = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dispatch"
    )

    # The allowlist comparison survives. It moved out of dispatch into
    # _host_is_served when wildcard support was added, so the guard follows it:
    # dispatch must still CALL the check, and the check must still consult the
    # allowlist. Asserting both keeps this a test that the exemption is a narrow
    # early return rather than a disabled check.
    assert "_host_is_served" in ast.dump(dispatch)
    assert "allowed_hosts_list" in source
    assert "InvalidHost" in source


# ---------------------------------------------------------------------------
# Prometheus points where we think it does
# ---------------------------------------------------------------------------


def test_prometheus_scrapes_the_api_at_the_expected_target():
    config = yaml.safe_load(PROMETHEUS.read_text())

    jobs = {j["job_name"]: j for j in config["scrape_configs"]}

    assert "fastapi" in jobs

    targets = jobs["fastapi"]["static_configs"][0]["targets"]

    assert targets == [SCRAPE_HOST], (
        "the scrape target changed; the exempted request is no longer the one "
        "Prometheus makes"
    )


def test_there_is_exactly_one_job_per_target():
    """A duplicate job silently doubles every counter it scrapes."""
    config = yaml.safe_load(PROMETHEUS.read_text())

    names = [j["job_name"] for j in config["scrape_configs"]]
    targets = [
        tuple(j["static_configs"][0]["targets"]) for j in config["scrape_configs"]
    ]

    assert len(names) == len(set(names)), f"duplicate job names: {names}"
    assert len(targets) == len(set(targets)), f"duplicate targets: {targets}"
