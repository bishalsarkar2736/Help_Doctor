"""Prometheus's TSDB survives being recreated.

WHAT THIS PREVENTS
prom/prometheus declares `VOLUME /prometheus` in its image. If compose does not
name that volume, Docker mints an ANONYMOUS one bound to a single container:
it survives `docker restart`, and dies on recreate. So the next
`docker compose up -d` touching this service starts with an empty TSDB and
orphans the old data under a 64-hex name nobody will ever identify.

Measured on this deployment before the volume was named: 22 blocks,
27.8 million samples, 14.3 days of history, one `up -d` away from silent loss.
The trap was that fixing it REQUIRES a recreate, so the change and the data loss
were the same event unless the data was copied across first.

Anonymous volumes are also invisible in review: `docker volume ls` showed 30
hex-named entries on this host, several of them almost certainly abandoned
TSDBs from earlier recreations, indistinguishable from live ones.

WHY A TEST AND NOT A COMMENT
The declaration is one line and deleting it looks harmless -- the stack still
starts, metrics still appear, and the loss only shows up the next time someone
recreates the service, by which point the data is gone.
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"
COMPOSE_STAGING = REPO / "docker-compose.staging.yml"

TSDB_PATH = "/prometheus"
VOLUME = "prometheus_data"

# Every service whose data must outlive a container recreate.
STATEFUL = {
    "postgres": "/var/lib/postgresql/data",
    "prometheus": TSDB_PATH,
    "alertmanager": "/alertmanager",
    "minio": "/data",
}


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates compose's `!override` tag."""


def _passthrough(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!", lambda loader, suffix, node: _passthrough(loader, node))


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_Loader)


def _mount_for(service: dict, target: str) -> str | None:
    for entry in service.get("volumes") or []:
        if isinstance(entry, str) and entry.split(":")[1:2] == [target]:
            return entry

    return None


# ---------------------------------------------------------------------------
# The TSDB is on a named volume
# ---------------------------------------------------------------------------


def test_prometheus_stores_its_tsdb_on_a_named_volume(compose):
    """THE REGRESSION. Without this the image's anonymous volume is used and a
    recreate discards every sample."""
    mount = _mount_for(compose["services"]["prometheus"], TSDB_PATH)

    assert mount is not None, (
        f"prometheus declares no volume for {TSDB_PATH}; the image's anonymous "
        "VOLUME is used instead and `docker compose up -d` silently discards "
        "the entire metrics history"
    )

    source = mount.split(":")[0]

    assert not source.startswith(("./", "/", "$")), (
        f"{TSDB_PATH} is bound to a host path ({source}); a named volume keeps "
        "the TSDB under Docker's management and off the developer's filesystem"
    )
    assert source == VOLUME, f"expected {VOLUME}, got {source}"


def test_the_volume_is_declared_at_the_top_level(compose):
    """An undeclared name in a service is an error, not an implicit volume."""
    assert VOLUME in (compose.get("volumes") or {}), (
        f"{VOLUME} is used by the prometheus service but not declared under the "
        "top-level `volumes:` key"
    )


def test_the_tsdb_mount_is_writable(compose):
    """Every other Prometheus mount is :ro. This one must not be."""
    mount = _mount_for(compose["services"]["prometheus"], TSDB_PATH)

    assert not mount.endswith(":ro"), f"the TSDB is mounted read-only: {mount}"


def test_the_config_mounts_stay_read_only(compose):
    """The counterpart: config is read-only so a stray write cannot mangle it."""
    for entry in compose["services"]["prometheus"]["volumes"]:
        target = entry.split(":")[1] if ":" in entry else ""

        if target.startswith("/etc/prometheus"):
            assert entry.endswith(":ro"), f"config mount is writable: {entry}"


# ---------------------------------------------------------------------------
# The same rule for every service holding state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service,target", sorted(STATEFUL.items()))
def test_stateful_services_use_named_volumes(compose, service, target):
    """Prometheus was the only one missing this. The parametrised form is what
    stops the next stateful service from being added without it."""
    mount = _mount_for(compose["services"][service], target)

    assert mount is not None, f"{service} has no named volume for {target}"

    source = mount.split(":")[0]

    assert source in (compose.get("volumes") or {}), (
        f"{service} mounts {target} from {source!r}, which is not a declared "
        "named volume"
    )


def test_no_stateful_service_relies_on_an_image_declared_volume(compose):
    """The failure mode in one assertion: a service that stores data and names
    no volume for it is one `up -d` from losing that data."""
    missing = [
        service for service, target in STATEFUL.items()
        if _mount_for(compose["services"][service], target) is None
    ]

    assert not missing, f"these store state on anonymous volumes: {missing}"


# ---------------------------------------------------------------------------
# Staging inherits it
# ---------------------------------------------------------------------------


def test_staging_does_not_override_the_prometheus_volumes():
    """Staging overrides only container_name and ports, so it gets the named
    volume too -- under its own project prefix, so the two never share a TSDB.
    """
    staging = yaml.load(COMPOSE_STAGING.read_text(), Loader=_Loader)["services"]

    assert "volumes" not in staging["prometheus"], (
        "staging overrides the prometheus volumes; it would then need its own "
        "named-volume declaration to avoid an anonymous TSDB"
    )
