"""The outbox dispatcher has a process to run in.

THE OUTAGE THIS CLOSES
app/workers/run_outbox_worker.py existed, was correct, was tested — and was
started by nothing. No compose service, no Procfile, no k8s manifest, no systemd
unit, no Dockerfile CMD, and deliberately not the API lifespan. Outside the test
suite the only references to it were from tests.

So every domain event the platform publishes was written to outbox_events and
consumed by nobody: in-app notifications, email, WhatsApp and the appointment
reminders. The dev database showed it plainly — 42 rows, all `pending`, the
oldest from two weeks earlier, and zero notifications.

WHY A SERVICE AND NOT A THREAD IN THE API
The worker must restart, scale and fail independently of the API, and an API
deploy must not interrupt a batch mid-flight. Starting it from the FastAPI
lifespan would couple all three.

WHAT THESE TESTS PIN
That the service exists in both environments, runs the real worker module, waits
for what it actually needs, publishes no port, and does not inherit either of the
two traps in this compose file: the image's HTTP healthcheck (there is no web
server) and celery_worker's Prometheus multiprocess setup (which is prefork-only,
and whose tmpfs once crash-looped that service on a permission error).
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"
COMPOSE_STAGING = REPO / "docker-compose.staging.yml"

SERVICE = "outbox_worker"
WORKER_MODULE = "app.workers.run_outbox_worker"


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates compose's `!override` tag.

    The staging file uses it on ports and env_file, and a plain SafeLoader raises
    on the unknown tag rather than reading the file.
    """


def _passthrough(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!", lambda loader, suffix, node: _passthrough(loader, node))


def _compose(path: pathlib.Path) -> dict:
    return yaml.load(path.read_text(), Loader=_Loader)


@pytest.fixture(scope="module")
def base() -> dict:
    return _compose(COMPOSE)["services"]


@pytest.fixture(scope="module")
def staging() -> dict:
    return _compose(COMPOSE_STAGING)["services"]


# ---------------------------------------------------------------------------
# The service exists and runs the real worker
# ---------------------------------------------------------------------------


def test_the_outbox_worker_service_exists(base):
    assert SERVICE in base, (
        "no service starts the outbox dispatcher; published events would be "
        "consumed by nobody"
    )


def test_the_command_runs_the_active_worker_module(base):
    command = base[SERVICE]["command"]

    text = " ".join(command) if isinstance(command, list) else str(command)

    assert WORKER_MODULE in text, f"command does not run the worker: {text!r}"
    assert "-m" in text, "run as a module, so __main__ reaches asyncio.run(main())"


def test_the_worker_module_it_names_actually_exists():
    """A command string is not checked by anything until deploy time."""
    path = REPO / pathlib.Path(WORKER_MODULE.replace(".", "/") + ".py")

    assert path.exists(), f"{WORKER_MODULE} does not exist"

    source = path.read_text()

    assert 'if __name__ == "__main__"' in source, (
        "the module has no __main__ guard, so `python -m` would do nothing"
    )


def test_it_does_not_reintroduce_the_legacy_processor(base):
    """The deleted parallel implementation must not come back through a compose
    command."""
    for name, service in base.items():
        command = service.get("command", "")
        text = " ".join(command) if isinstance(command, list) else str(command)

        assert "outbox_tasks_old" not in text, f"{name} runs the legacy processor"
        assert "process_outbox_events" not in text, (
            f"{name} runs the legacy task"
        )


def test_only_one_service_runs_the_outbox_worker(base):
    runners = [
        name for name, service in base.items()
        if WORKER_MODULE in (
            " ".join(service["command"])
            if isinstance(service.get("command"), list)
            else str(service.get("command", ""))
        )
    ]

    assert runners == [SERVICE], f"expected one outbox runner, found {runners}"


def test_the_api_does_not_start_the_worker():
    """Explicitly not in the lifespan: the worker must fail and restart on its
    own, and an API deploy must not interrupt a batch."""
    main = (REPO / "app" / "main.py").read_text()

    assert "run_outbox_worker" not in main
    assert "process_outbox" not in main


# ---------------------------------------------------------------------------
# It waits for what it needs, and nothing it does not
# ---------------------------------------------------------------------------


def test_it_waits_for_postgres_and_redis(base):
    """Postgres because the loop selects and advances outbox rows. Redis because
    the dispatch path uses it for the notification cooldown, the push-enqueue
    idempotency claim, and as the Celery broker when a handler enqueues a push.
    """
    depends = base[SERVICE]["depends_on"]

    assert depends["postgres"]["condition"] == "service_healthy"
    assert depends["redis"]["condition"] == "service_healthy"


def test_it_waits_for_the_migration_to_finish(base):
    """A worker that starts before the schema exists spends its first minutes
    crash-looping on missing columns."""
    depends = base[SERVICE]["depends_on"]

    assert depends["migrate"]["condition"] == "service_completed_successfully"


def test_it_depends_on_nothing_else(base):
    """Minimal on purpose — a dependency here delays startup and couples the
    worker to a service it does not use."""
    assert set(base[SERVICE]["depends_on"]) == {"migrate", "postgres", "redis"}


# ---------------------------------------------------------------------------
# Configuration, ports and restart behaviour
# ---------------------------------------------------------------------------


def test_it_receives_the_same_configuration_as_the_api(base):
    """Same env_file, so the worker cannot drift onto a different database,
    Redis, or set of feature flags than the process publishing the events."""
    assert base[SERVICE]["env_file"] == base["api"]["env_file"]


def test_it_publishes_no_port(base):
    """Nothing about this process is reachable from outside the network."""
    assert "ports" not in base[SERVICE], "the outbox worker publishes a port"
    assert "expose" not in base[SERVICE]


def test_it_restarts_after_failure(base):
    assert base[SERVICE]["restart"] == "unless-stopped"


def test_it_does_not_inherit_the_images_http_healthcheck(base):
    """The image's HEALTHCHECK curls :8000/health/live, which this service does
    not serve — inheriting it reports a permanently false "unhealthy".

    This used to assert the healthcheck was DISABLED, which was correct while the
    worker exposed nothing to probe. It now serves its metrics endpoint, so the
    same intent is met by overriding the probe rather than switching it off: the
    check must exist, and must not be the image's :8000 one.
    """
    healthcheck = base[SERVICE].get("healthcheck")

    assert healthcheck is not None, "the image's HTTP healthcheck is inherited"

    if healthcheck.get("disable") is True:
        return

    probe = " ".join(healthcheck["test"])

    assert "8000" not in probe, "still probing the API's port"
    assert "/health/live" not in probe


def test_it_avoids_the_prometheus_multiproc_setup(base):
    """celery_worker's PROMETHEUS_MULTIPROC_DIR + tmpfs is prefork-only
    machinery: this service is a single asyncio loop with no pool children whose
    metrics need aggregating, and it exports its own directly. Copying the setup
    would also have inherited the tmpfs permission crash that service hit, since
    fixed by pinning mode=1777 on the mount."""
    service = base[SERVICE]

    assert "tmpfs" not in service
    assert "PROMETHEUS_MULTIPROC_DIR" not in (service.get("environment") or {})


def test_it_is_built_from_the_application_image(base):
    """Same image as the api and celery services, so the worker runs the code
    that was built and tested, not a second build."""
    assert base[SERVICE]["image"] == base["api"]["image"]
    assert base[SERVICE]["build"] == base["api"]["build"]


# ---------------------------------------------------------------------------
# Staging gets it too
# ---------------------------------------------------------------------------


def test_staging_defines_the_service(staging):
    """Staging is where deployment is rehearsed. A service missing there is a
    difference between the rehearsal and the thing being rehearsed."""
    assert SERVICE in staging


def test_staging_overrides_the_container_name(staging):
    """container_name is global rather than scoped by compose project, so
    without this the second stack collides before it reaches a port."""
    assert staging[SERVICE]["container_name"] == "staging_outbox_worker"


def test_staging_overrides_the_environment_file(staging):
    """env_file MERGES across compose files. Without !override, staging silently
    keeps production's value for every key .env.staging does not define — which
    is how a staging run once reached the production database."""
    assert staging[SERVICE]["env_file"] == [".env.staging"]


def test_staging_publishes_no_port_for_the_worker(staging):
    assert "ports" not in staging[SERVICE]


def test_every_app_service_in_staging_overrides_both(staging, base):
    """The rule the whole staging file exists for, applied to the new service
    alongside the existing ones."""
    app_services = {
        name for name, service in base.items()
        if service.get("image") == base["api"]["image"]
    }

    for name in app_services:
        assert name in staging, f"{name} has no staging override"
        assert "container_name" in staging[name]
        assert staging[name].get("env_file") == [".env.staging"], (
            f"{name} does not override env_file in staging"
        )
