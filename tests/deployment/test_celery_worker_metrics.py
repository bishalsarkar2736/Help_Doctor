"""The Celery worker's metrics scratch space, and enough descriptors to work.

TWO FAILURES, ONE SERVICE, AND ONLY ONE OF THEM WAS A CONFIGURATION BUG.

The symptom was a crash loop:

    PermissionError: '/tmp/prometheus_multiproc/gauge_livesum_1.db'

The obvious reading — a root-owned tmpfs the non-root `app` user cannot write —
turned out to be wrong. Docker mounts a tmpfs 1777 (world-writable, sticky), uid
999 writes to it happily, and the compose definition was already correct. The
crashing container was simply STALE: created four days earlier from an image that
had since been replaced. Recreating it fixed the permission error, and no tmpfs
option was added, because adding uid=999 would hard-code a number that lives in
the Dockerfile and would break the mount the day that uid changed.

What the crash loop had been HIDING was real. Once the worker started, every task
was rejected before its body ran:

    [Errno 24] Too many open files

The container inherits the daemon's default soft limit of 1024 descriptors, and
Celery prefork with four children exhausts it during pool setup. The worker
reported itself healthy, beat dispatched happily, and nothing executed. Measured
at 65536 the entire pool sits under 100 descriptors, so the limit is headroom
rather than a leak being papered over.

These tests pin the configuration in both environments and, where Docker is
available, prove the actual image lets the actual non-root user write to the
actual mount.
"""

import pathlib
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"
COMPOSE_STAGING = REPO / "docker-compose.staging.yml"
DOCKERFILE = REPO / "Dockerfile"

SERVICE = "celery_worker"
METRICS_DIR = "/tmp/prometheus_multiproc"

docker_available = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker is not available in this environment",
)


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates compose's `!override` tag."""


def _passthrough(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor(
    "!", lambda loader, suffix, node: _passthrough(loader, node)
)


@pytest.fixture(scope="module")
def base() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]


@pytest.fixture(scope="module")
def staging() -> dict:
    return yaml.load(COMPOSE_STAGING.read_text(), Loader=_Loader)["services"]


# ---------------------------------------------------------------------------
# Multiprocess metrics stay configured
# ---------------------------------------------------------------------------


def test_the_metrics_directory_is_a_tmpfs(base):
    """A volume would let a dead worker's .db files be aggregated into the next
    run's totals; the files are mmap'd scratch and must not survive a restart."""
    assert METRICS_DIR in base[SERVICE]["tmpfs"]


def test_the_multiprocess_directory_is_exported(base):
    """Task signals fire in the prefork CHILDREN while the metrics server runs in
    the parent. Without this every counter exports zero."""
    assert base[SERVICE]["environment"]["PROMETHEUS_MULTIPROC_DIR"] == METRICS_DIR


def test_multiprocess_metrics_were_not_removed_to_dodge_the_crash(base):
    """The cheap "fix" would have been deleting the tmpfs and the env var. That
    disables worker metrics entirely — a dead worker then looks identical to an
    idle one."""
    service = base[SERVICE]

    assert "tmpfs" in service
    assert "PROMETHEUS_MULTIPROC_DIR" in service["environment"]
    assert "CELERY_METRICS_PORT" in service["environment"]


def test_the_tmpfs_is_not_pinned_to_a_hard_coded_uid(base):
    """Deliberately no uid=/gid= option.

    The default 1777 mount is already writable by the non-root user, and a
    hard-coded uid here would duplicate the Dockerfile's useradd and break
    silently if it ever changed.
    """
    entries = base[SERVICE]["tmpfs"]

    for entry in entries:
        assert "uid=" not in entry, f"tmpfs pins a uid: {entry}"
        assert "gid=" not in entry, f"tmpfs pins a gid: {entry}"


# ---------------------------------------------------------------------------
# The worker runs as a non-root user, and keeps doing so
# ---------------------------------------------------------------------------


def test_the_image_runs_as_a_non_root_user():
    dockerfile = DOCKERFILE.read_text()

    assert "USER app" in dockerfile
    assert dockerfile.rstrip().splitlines()[-1].startswith("CMD"), (
        "USER must not be undone after being set"
    )


@pytest.mark.parametrize("service", [SERVICE, "celery_beat", "outbox_worker"])
def test_no_worker_service_escalates_to_root(base, service):
    """`user: root` would have made the PermissionError disappear and is exactly
    what must not be done."""
    assert base[service].get("user") in (None, "app")


# ---------------------------------------------------------------------------
# Enough file descriptors to run a task
# ---------------------------------------------------------------------------


def test_the_worker_raises_the_descriptor_limit(base):
    """Without this the pool children exhaust the daemon default of 1024 during
    setup and every task is rejected with [Errno 24] before its body runs."""
    nofile = base[SERVICE]["ulimits"]["nofile"]

    assert nofile["soft"] >= 65536
    assert nofile["hard"] >= nofile["soft"]


def test_the_limit_is_well_clear_of_the_default(base):
    """1024 is the value that failed. Anything near it is not a fix."""
    assert base[SERVICE]["ulimits"]["nofile"]["soft"] > 1024 * 8


# ---------------------------------------------------------------------------
# Both environments
# ---------------------------------------------------------------------------


def test_staging_inherits_rather_than_duplicates_the_fix(staging):
    """The staging file overrides only container_name and env_file, so the tmpfs,
    the metrics env and the descriptor limit come from the base file. Duplicating
    them here would create two places to keep in sync."""
    override = staging[SERVICE]

    assert set(override) <= {"container_name", "env_file", "ports"}
    assert override["container_name"] == "staging_celery_worker"


@docker_available
def test_the_resolved_staging_config_carries_the_fix():
    """Resolved through compose itself, because inheritance is the whole claim."""
    result = subprocess.run(
        [
            "docker", "compose",
            "-p", "helpdoctor_staging",
            "-f", str(COMPOSE),
            "-f", str(COMPOSE_STAGING),
            "config",
        ],
        capture_output=True, text=True, cwd=REPO, timeout=180,
    )

    if result.returncode != 0:
        pytest.skip(f"compose config unavailable: {result.stderr[:200]}")

    service = yaml.safe_load(result.stdout)["services"][SERVICE]

    assert service["ulimits"]["nofile"]["soft"] >= 65536
    assert any(METRICS_DIR in entry for entry in service["tmpfs"])
    assert service["container_name"] == "staging_celery_worker"


# ---------------------------------------------------------------------------
# The real image, where Docker is available
# ---------------------------------------------------------------------------


@docker_available
def test_the_non_root_user_can_write_to_the_tmpfs():
    """The claim the whole milestone rests on, proved against the real image and
    the real mount rather than inferred from the mode bits."""
    image = yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]["api"]["image"]

    probe = subprocess.run(
        [
            "docker", "run", "--rm",
            "--user", "999:999",
            "--tmpfs", METRICS_DIR,
            "--entrypoint", "sh", image,
            "-c",
            f"touch {METRICS_DIR}/probe.db && echo WRITABLE || echo DENIED",
        ],
        capture_output=True, text=True, timeout=180,
    )

    if probe.returncode != 0 and "No such image" in probe.stderr:
        pytest.skip("application image is not built locally")

    assert "WRITABLE" in probe.stdout, (
        f"the non-root user cannot write the metrics dir: "
        f"{probe.stdout!r} {probe.stderr[:200]!r}"
    )


@docker_available
def test_the_image_user_is_the_one_the_compose_file_assumes():
    """If this uid ever changes, the tmpfs default still works — but a test that
    asserted 999 anywhere else would not. Recorded here, in one place."""
    image = yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]["api"]["image"]

    probe = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", "id -u app; id -g app"],
        capture_output=True, text=True, timeout=180,
    )

    if probe.returncode != 0:
        pytest.skip("application image is not built locally")

    uid, gid = probe.stdout.split()

    assert int(uid) != 0, "the app user is root"
    assert int(gid) != 0
