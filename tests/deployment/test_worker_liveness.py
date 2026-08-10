"""Telling "the process is up" apart from "work is getting done".

THE GAP
celery_worker's health signal was `celery inspect ping`, which answers from the
prefork PARENT. When the pool could not start a task -- it had exhausted its file
descriptors and rejected every one with [Errno 24] -- the parent still answered,
the container still reported healthy, and nothing ran for hours.

outbox_worker and celery_beat had no signal at all: `healthcheck: disable: true`.

And outbox_worker_heartbeat, the obvious answer, was a trap. It has existed and
been refreshed on every poll for as long as the worker has -- but that process
runs no HTTP server and Prometheus had no job for it, so the gauge was set in
memory nothing could read. Unobservable, not merely unwatched.

THE SEMANTICS, KEPT SEPARATE ON PURPOSE

    liveness   the process exists and answers
    progress   work has actually moved recently

A container healthcheck can only honestly answer the first: /metrics is served
from its own thread and keeps answering a wedged loop. So the healthcheck claims
liveness and nothing more, and progress is asserted by Prometheus rules against
metrics the loop itself advances. These tests pin that split, because the
tempting mistake is to let one stand in for the other.
"""

import ast
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"
PROMETHEUS = REPO / "prometheus.yml"
ALERTS = REPO / "alerts.yml"
RUNNER = REPO / "app" / "workers" / "run_outbox_worker.py"


class _Loader(yaml.SafeLoader):
    """SafeLoader tolerating compose's `!override` tag."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node)
    ),
)


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]


@pytest.fixture(scope="module")
def prometheus() -> dict:
    return yaml.safe_load(PROMETHEUS.read_text())


@pytest.fixture(scope="module")
def rules() -> dict:
    by_name = {}

    for group in yaml.safe_load(ALERTS.read_text())["groups"]:
        for rule in group["rules"]:
            by_name[rule["alert"]] = rule

    return by_name


# ---------------------------------------------------------------------------
# The heartbeat is real: updated, and reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_loop_refreshes_the_heartbeat(monkeypatch):
    """The gauge must be advanced by the thing whose progress it claims to
    report, not merely once at startup."""
    import time as time_module

    from app.core.metrics import outbox_worker_heartbeat
    from app.workers import outbox_worker

    async def _empty_batch(db):
        return 0

    monkeypatch.setattr(outbox_worker, "process_batch", _empty_batch)

    outbox_worker_heartbeat.set(0)

    before = time_module.time()

    await outbox_worker.process_outbox()

    beat = outbox_worker_heartbeat._value.get()

    assert beat >= before, "the poll did not refresh the heartbeat"


def test_the_worker_starts_a_metrics_server():
    """Without this the heartbeat is set in memory nobody can read.

    Asserted on the code as well as behaviourally below, because the failure
    mode is silent: everything works, and the gauge is simply invisible.
    """
    tree = ast.parse(RUNNER.read_text())

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "start_http_server" in called

    main = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )

    started = {
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_start_metrics_server" in started, (
        "the metrics server is defined but never started by main()"
    )


def test_the_heartbeat_can_actually_be_scraped():
    """End to end over HTTP, against the real exporter."""
    import urllib.request

    from prometheus_client import start_http_server

    from app.core.metrics import outbox_worker_heartbeat

    outbox_worker_heartbeat.set(1234567890.0)

    port = 9187

    try:
        start_http_server(port)
    except OSError:
        pass  # already bound by an earlier run in this session

    body = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/metrics", timeout=5
    ).read().decode()

    assert "outbox_worker_heartbeat 1.23456789e+09" in body


def test_the_metrics_server_failure_does_not_stop_the_worker():
    """Metrics are how the outbox is watched; they are not the outbox. A bound
    port must not take the dispatcher down."""
    from app.workers import run_outbox_worker

    source = ast.parse(RUNNER.read_text())

    function = next(
        node for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_start_metrics_server"
    )

    handlers = [n for n in ast.walk(function) if isinstance(n, ast.ExceptHandler)]

    assert handlers, "a port clash would crash the worker"

    # And it really does swallow it.
    run_outbox_worker._start_metrics_server()
    run_outbox_worker._start_metrics_server()


# ---------------------------------------------------------------------------
# Prometheus can reach it, on the port the container actually serves
# ---------------------------------------------------------------------------


def test_prometheus_scrapes_the_outbox_worker(prometheus):
    jobs = {j["job_name"] for j in prometheus["scrape_configs"]}

    assert "outbox_worker" in jobs


def test_the_scrape_port_matches_what_the_container_serves(
    prometheus, services
):
    """Three places have to agree, and nothing at runtime would say if they did
    not -- the target would simply sit DOWN."""
    target = next(
        j["static_configs"][0]["targets"][0]
        for j in prometheus["scrape_configs"]
        if j["job_name"] == "outbox_worker"
    )
    host, _, scrape_port = target.partition(":")

    assert host == "outbox_worker", "the target must be the compose service name"

    configured = str(services["outbox_worker"]["environment"]["OUTBOX_METRICS_PORT"])

    assert scrape_port == configured

    healthcheck = " ".join(services["outbox_worker"]["healthcheck"]["test"])

    assert configured in healthcheck, (
        "the healthcheck probes a different port than the one exported"
    )


def test_the_metrics_port_is_not_published_to_the_host(services):
    """Internal to the compose network. Prometheus is on it; nothing else needs
    to be."""
    assert "ports" not in services["outbox_worker"]


# ---------------------------------------------------------------------------
# The container healthcheck claims liveness, and only liveness
# ---------------------------------------------------------------------------


def test_the_outbox_worker_has_a_healthcheck(services):
    healthcheck = services["outbox_worker"].get("healthcheck", {})

    assert healthcheck.get("disable") is not True, (
        "the outbox worker still has no health signal at all"
    )
    assert healthcheck.get("test")


def test_the_healthcheck_probes_the_process_not_the_database(services):
    """It must not become a second readiness probe: a healthcheck that fails
    when Postgres is unreachable restarts a worker that is not the problem."""
    healthcheck = " ".join(services["outbox_worker"]["healthcheck"]["test"])

    for forbidden in ("psql", "pg_isready", "alembic", "redis-cli"):
        assert forbidden not in healthcheck


def test_no_worker_service_runs_as_root(services):
    for name in ("celery_worker", "celery_beat", "outbox_worker"):
        assert services[name].get("user") in (None, "app")


# ---------------------------------------------------------------------------
# Progress is asserted where it can be: the alert rules
# ---------------------------------------------------------------------------


def test_liveness_and_progress_are_separate_rules(rules):
    """The distinction the whole milestone is about. One rule may not stand in
    for the other."""
    assert "OutboxWorkerDown" in rules
    assert "OutboxWorkerStalled" in rules

    assert "up{job=" in rules["OutboxWorkerDown"]["expr"]
    assert "outbox_worker_heartbeat" in rules["OutboxWorkerStalled"]["expr"]

    # The progress rule must not be a disguised liveness check.
    assert "up{" not in rules["OutboxWorkerStalled"]["expr"]


def test_the_stall_threshold_is_wider_than_the_poll_interval(rules):
    """A threshold below POLL_INTERVAL would page on every normal cycle."""
    import re

    from app.workers.run_outbox_worker import POLL_INTERVAL

    seconds = int(
        re.search(r"outbox_worker_heartbeat\{[^}]*\}\s*>\s*(\d+)",
                  rules["OutboxWorkerStalled"]["expr"]).group(1)
    )

    assert seconds > POLL_INTERVAL * 4, (
        f"{seconds}s is too tight for a {POLL_INTERVAL}s poll"
    )


def test_celery_execution_health_is_not_a_ping(rules):
    """The specific false negative that started this: ping answered while the
    pool rejected everything. The rule must ask about completed work."""
    expr = rules["CeleryWorkerNotExecuting"]["expr"]

    assert "celery_tasks_total" in expr
    assert "increase(" in expr

    # Scoped, or it matches the api process, which defines these gauges at
    # import time and leaves them at zero.
    assert 'job="celery"' in expr


def test_the_execution_rule_does_not_fire_for_a_dead_worker(rules):
    """Otherwise it double-pages with CeleryWorkerDown for one incident."""
    assert "celery_worker_up" in rules["CeleryWorkerNotExecuting"]["expr"]


def test_a_stopped_beat_is_distinguishable_from_a_wedged_worker(rules):
    """Same silence, different cause: a wedged worker leaves the queue growing,
    a dead beat leaves it empty."""
    assert "CeleryBeatNotDispatching" in rules
    assert "celery_queue_length" in rules["CeleryBeatNotDispatching"]["expr"]


@pytest.mark.parametrize(
    "alert",
    [
        "OutboxWorkerDown",
        "OutboxWorkerStalled",
        "CeleryWorkerNotExecuting",
        "CeleryBeatNotDispatching",
    ],
)
def test_every_new_rule_is_actionable(rules, alert):
    """An alert that does not say what broke or what it means wakes someone up
    for nothing."""
    rule = rules[alert]

    assert rule["annotations"]["summary"]
    assert len(rule["annotations"]["description"]) > 60
    assert rule["labels"]["severity"] in {"critical", "warning"}
    assert rule.get("for"), "no `for:` means a single scrape blip pages someone"
