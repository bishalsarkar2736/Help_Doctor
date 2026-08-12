"""Alertmanager can read the credentials it is configured to deliver with.

THE FAILURE, REPRODUCED BEFORE THIS WAS WRITTEN
prom/alertmanager runs as nobody (65534). The mounted secrets are 0600 owned by
the deploying user. Every layer that could catch that says the system is fine:

    amtool check-config          SUCCESS, exit 0
    container start              running, exit 0, no permission error
    POST /api/v2/alerts          200, alert shows "active"
    Prometheus                   alert firing

and then nothing arrives:

    notify retry canceled due to unrecoverable error after 1 attempts:
    open /etc/alertmanager/secrets/slack_webhook: permission denied

    find auth mechanism: could not read
    /etc/alertmanager/secrets/smtp_password: permission denied

Measured in a throwaway stack: 54 attempts, 54 failures, 0 delivered. chmod 644
restored delivery immediately.

WHY THE DEPLOY GATE IS THE ONLY PLACE TO CATCH IT
This is the same root cause as the Prometheus metrics token, minus both of that
bug's safety nets. promtool exits 1 on an unreadable bearer_token_file; amtool
does not. A failed scrape takes the target DOWN and fires APIDown; a failed
notification increments alertmanager_notifications_failed_total, which no scrape
job collects and no rule reads. Nothing else can tell you.

WHAT THESE TESTS PIN
That the required files are DERIVED from alertmanager.production.yml rather than
hard-coded, that every reference stays inside the mounted directory, and that the
gate rejects exactly the states that fail at runtime and accepts exactly those
that work -- including the 65534-owned 0600 case, which is legitimate.
"""

import os
import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

CONFIG = REPO / "alertmanager.production.yml"
DEV_CONFIG = REPO / "alertmanager.yml"
COMPOSE = REPO / "docker-compose.yml"
GITIGNORE = REPO / ".gitignore"

MOUNT = "/etc/alertmanager/secrets"


def _required_secret_names() -> list[str]:
    """The secret files alertmanager.production.yml actually declares.

    Derived, not listed. When the watchdog receiver was added these fixtures
    hard-coded {slack_webhook, smtp_password} and three of them failed -- which
    is the derivation working, but it also meant the fixtures asserted the very
    thing they warn the implementation against. Reading the config keeps them
    correct for whatever receiver comes next.
    """
    import yaml as _yaml

    config = _yaml.safe_load((REPO / "alertmanager.production.yml").read_text())

    return sorted(
        reference.split(MOUNT + "/", 1)[1]
        for reference in _gate().alertmanager_secret_references(config)
    )


def _gate():
    import importlib

    return importlib.import_module("scripts.check_production_env")

# Documentation that must never tell an operator to lock a mounted secret to a
# uid the container does not run as.
DOCS = ["docs/DEPLOYMENT.md", "docs/MONITORING.md", "docs/CONFIGURATION.md",
        "docs/OPERATIONS.md", ".env.example", "alertmanager.production.yml",
        "alertmanager.yml", "prometheus.yml", "prometheus.production.yml"]


@pytest.fixture(scope="module")
def gate():
    import importlib

    return importlib.import_module("scripts.check_production_env")


@pytest.fixture
def clean_gate(gate):
    """The module accumulates results in globals; isolate each test."""
    gate.ERRORS.clear()
    gate.WARNINGS.clear()
    gate.OK.clear()

    yield gate

    gate.ERRORS.clear()
    gate.WARNINGS.clear()
    gate.OK.clear()


@pytest.fixture
def secrets_dir(clean_gate, tmp_path, monkeypatch):
    """A throwaway repo root whose secrets/ the gate will inspect."""
    monkeypatch.setattr(clean_gate, "REPO", tmp_path)

    directory = tmp_path / "secrets"
    directory.mkdir()

    return directory


def _stat_as(monkeypatch, target: Path, *, mode: int, uid: int, gid: int) -> None:
    """Present `target` to the gate with the given mode/owner.

    chown needs root, and the 65534-owned case is exactly the one that cannot be
    created in an ordinary test run -- so the stat is doctored for that one path
    and delegated for every other.
    """
    original = Path.stat

    def fake(self, *args, **kwargs):
        real = original(self, *args, **kwargs)

        if self == target:
            return os.stat_result((
                (real.st_mode & ~0o777) | mode,
                real.st_ino, real.st_dev, real.st_nlink,
                uid, gid, real.st_size,
                int(real.st_atime), int(real.st_mtime), int(real.st_ctime),
            ))

        return real

    monkeypatch.setattr(Path, "stat", fake)


# ---------------------------------------------------------------------------
# 1 & 2. The required files are derived from the config and resolve inside the mount
# ---------------------------------------------------------------------------


def test_the_production_config_exists():
    assert CONFIG.is_file()


def test_every_secret_reference_resolves_inside_the_mounted_directory(gate):
    config = yaml.safe_load(CONFIG.read_text())

    references = gate.alertmanager_secret_references(config)

    assert references, "the production config reads no *_file secrets"

    for reference in references:
        assert reference.startswith(MOUNT + "/"), (
            f"{reference} is outside {MOUNT}, which is the only directory "
            "compose mounts — the file would not exist at runtime"
        )


def test_the_references_are_the_ones_the_config_actually_declares(gate):
    """Derived, not hard-coded: the point is that adding a receiver with a new
    credential is covered automatically."""
    config = yaml.safe_load(CONFIG.read_text())

    references = set(gate.alertmanager_secret_references(config))

    assert references == {
        f"{MOUNT}/{name}" for name in _required_secret_names()
    }, references

    # The set is derived, but it must not be EMPTY -- a config that declares no
    # secrets would make every check below vacuous.
    assert len(references) >= 3, references


def test_secret_references_are_found_however_deeply_nested(gate):
    """api_url_file sits under receivers[].slack_configs[]; smtp_auth_password_file
    sits under global. A flat scan would miss one of them."""
    found = gate.alertmanager_secret_references({
        "global": {"smtp_auth_password_file": f"{MOUNT}/a"},
        "receivers": [
            {"name": "x", "slack_configs": [{"api_url_file": f"{MOUNT}/b"}]},
            {"name": "y", "webhook_configs": [
                {"http_config": {"bearer_token_file": f"{MOUNT}/c"}}
            ]},
        ],
    })

    assert set(found) == {f"{MOUNT}/a", f"{MOUNT}/b", f"{MOUNT}/c"}


def test_non_secret_keys_are_not_mistaken_for_secrets(gate):
    found = gate.alertmanager_secret_references({
        "templates": ["/etc/alertmanager/templates/*.tmpl"],
        "global": {"smtp_smarthost": "smtp.example.com:587"},
    })

    assert found == []


def test_compose_mounts_the_directory_the_config_reads_from():
    import yaml as y

    class Loader(y.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: (
        loader.construct_sequence(node) if isinstance(node, y.SequenceNode)
        else loader.construct_mapping(node) if isinstance(node, y.MappingNode)
        else loader.construct_scalar(node)
    ))

    volumes = y.load(COMPOSE.read_text(), Loader=Loader)["services"]["alertmanager"]["volumes"]

    mounted = [v for v in volumes if v.split(":")[1] == MOUNT]

    assert mounted, f"alertmanager does not mount {MOUNT}"
    assert mounted[0].endswith(":ro"), f"the secret mount is writable: {mounted[0]!r}"


# ---------------------------------------------------------------------------
# 3-6. The gate accepts exactly the states that work at runtime
# ---------------------------------------------------------------------------


def test_a_missing_secret_is_rejected(clean_gate, secrets_dir):
    """Nothing else notices: Alertmanager starts and amtool passes."""
    clean_gate.check_alertmanager_secrets({})

    assert any("does not exist" in e for e in clean_gate.ERRORS), clean_gate.ERRORS


def test_a_secret_unreadable_by_the_container_is_rejected(clean_gate, secrets_dir):
    """0600 owned by the deploying user — the reproduced production failure."""
    for name in _required_secret_names():
        secret = secrets_dir / name
        secret.write_text("placeholder")
        secret.chmod(0o600)

    clean_gate.check_alertmanager_secrets({})

    failures = [e for e in clean_gate.ERRORS if "cannot read it" in e]

    assert len(failures) == len(_required_secret_names()), clean_gate.ERRORS
    assert all("alerts fire and reach nobody" in e for e in failures)


def test_a_secret_at_0640_is_still_rejected(clean_gate, secrets_dir):
    """Measured: 0640 fails too. Group access does not help when the container's
    gid is not the file's gid."""
    for name in _required_secret_names():
        secret = secrets_dir / name
        secret.write_text("placeholder")
        secret.chmod(0o640)

    clean_gate.check_alertmanager_secrets({})

    assert any("cannot read it" in e for e in clean_gate.ERRORS)


def test_a_readable_644_secret_is_accepted(clean_gate, secrets_dir):
    """The documented simple convention."""
    for name in _required_secret_names():
        secret = secrets_dir / name
        secret.write_text("placeholder")
        secret.chmod(0o644)

    clean_gate.check_alertmanager_secrets({})

    assert clean_gate.ERRORS == []
    assert len([o for o in clean_gate.OK if "readable by Alertmanager" in o]) == len(
        _required_secret_names()
    )


def test_a_600_secret_owned_by_the_container_uid_is_accepted(
    clean_gate, secrets_dir, monkeypatch
):
    """The documented alternative for hosts with untrusted local users:
    chown 65534 + chmod 600. It must not be reported as a failure."""
    for name in _required_secret_names():
        secret = secrets_dir / name
        secret.write_text("placeholder")
        secret.chmod(0o600)

    # Both files, presented as owned by nobody.
    original = Path.stat
    targets = {secrets_dir / name for name in _required_secret_names()}

    def fake(self, *args, **kwargs):
        real = original(self, *args, **kwargs)

        if self in targets:
            return os.stat_result((
                (real.st_mode & ~0o777) | 0o600,
                real.st_ino, real.st_dev, real.st_nlink,
                clean_gate.SECRET_READER_UID, clean_gate.SECRET_READER_UID,
                real.st_size,
                int(real.st_atime), int(real.st_mtime), int(real.st_ctime),
            ))

        return real

    monkeypatch.setattr(Path, "stat", fake)

    clean_gate.check_alertmanager_secrets({})

    assert clean_gate.ERRORS == [], clean_gate.ERRORS


def test_a_group_readable_secret_owned_by_the_container_gid_is_accepted(
    clean_gate, secrets_dir, monkeypatch
):
    names = _required_secret_names()

    # The first is presented as group-readable and owned by the container's gid;
    # the rest are plainly readable, so only the doctored one is under test.
    secret = secrets_dir / names[0]

    for name in names:
        path = secrets_dir / name
        path.write_text("placeholder")
        path.chmod(0o640 if name == names[0] else 0o644)

    _stat_as(monkeypatch, secret, mode=0o640, uid=0, gid=clean_gate.SECRET_READER_UID)

    clean_gate.check_alertmanager_secrets({})

    assert clean_gate.ERRORS == [], clean_gate.ERRORS


def test_a_directory_where_a_secret_should_be_is_rejected(clean_gate, secrets_dir):
    """Docker silently creates a DIRECTORY for a missing bind-mount source; the
    same shape here would otherwise pass an exists() check."""
    (secrets_dir / "slack_webhook").mkdir()
    (secrets_dir / "smtp_password").write_text("placeholder")
    (secrets_dir / "smtp_password").chmod(0o644)

    clean_gate.check_alertmanager_secrets({})

    assert any("not a regular file" in e for e in clean_gate.ERRORS), clean_gate.ERRORS


# ---------------------------------------------------------------------------
# 10. A reference cannot escape the mounted directory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/alertmanager/secrets/../../../etc/passwd",
        "/etc/passwd",
        "/etc/alertmanager/alertmanager.yml",
        "secrets/slack_webhook",
        "/etc/alertmanager/secretsevil/token",
    ],
)
def test_a_reference_outside_the_mount_is_rejected(
    clean_gate, secrets_dir, monkeypatch, reference
):
    monkeypatch.setattr(
        clean_gate, "ALERTMANAGER_PRODUCTION_CONFIG", secrets_dir.parent / "am.yml"
    )

    (secrets_dir.parent / "am.yml").write_text(
        "receivers:\n"
        "  - name: x\n"
        "    slack_configs:\n"
        f"      - api_url_file: {reference}\n"
    )

    clean_gate.check_alertmanager_secrets({})

    assert any("outside" in e for e in clean_gate.ERRORS), (
        f"{reference} was not rejected: {clean_gate.ERRORS}"
    )


def test_a_nested_path_inside_the_mount_is_allowed(clean_gate, secrets_dir, monkeypatch):
    """Rejecting escape must not reject legitimate sub-directories."""
    monkeypatch.setattr(
        clean_gate, "ALERTMANAGER_PRODUCTION_CONFIG", secrets_dir.parent / "am.yml"
    )

    (secrets_dir.parent / "am.yml").write_text(
        "receivers:\n"
        "  - name: x\n"
        "    slack_configs:\n"
        f"      - api_url_file: {MOUNT}/team/webhook\n"
    )

    nested = secrets_dir / "team"
    nested.mkdir()
    (nested / "webhook").write_text("placeholder")
    (nested / "webhook").chmod(0o644)

    clean_gate.check_alertmanager_secrets({})

    assert clean_gate.ERRORS == [], clean_gate.ERRORS


# ---------------------------------------------------------------------------
# 7. Development and staging are untouched
# ---------------------------------------------------------------------------


def test_the_development_config_requires_no_mounted_secret(gate):
    """Dev points at MailHog with no credential, which is why local work does not
    need a secrets directory at all."""
    config = yaml.safe_load(DEV_CONFIG.read_text())

    assert gate.alertmanager_secret_references(config) == []


def test_the_production_config_is_not_the_default(gate):
    """The check applies to production. Development and staging keep the dev
    config, so nothing about this milestone changes how they start."""
    text = COMPOSE.read_text()

    assert "${ALERTMANAGER_CONFIG:-./alertmanager.yml}" in text


def test_the_check_is_actually_wired_into_the_gate(clean_gate, tmp_path, monkeypatch):
    """A correct check that nothing calls is worth nothing.

    Found by mutation: deleting `check_alertmanager_secrets(env)` from `check()`
    left every other test in this file passing, because they all called the
    function directly. This one goes through the gate's own entry point.
    """
    monkeypatch.setattr(clean_gate, "REPO", tmp_path)

    secrets = tmp_path / "secrets"
    secrets.mkdir()

    for name in _required_secret_names():
        secret = secrets / name
        secret.write_text("placeholder")
        secret.chmod(0o600)

    # check() re-reads the env file from sys.argv[1] for its duplicate-key scan,
    # so it has to be given one. Under pytest sys.argv[1] is a pytest argument.
    env_file = tmp_path / ".env.production"
    env_file.write_text("ENV=production\nMETRICS_TOKEN=placeholder\n")
    monkeypatch.setattr(sys, "argv", ["check_production_env.py", str(env_file)])

    clean_gate.check({"ENV": "production", "METRICS_TOKEN": "placeholder"})

    assert any("alerts fire and reach nobody" in e for e in clean_gate.ERRORS), (
        "check() does not run the Alertmanager secret validation"
    )


def test_the_gate_reports_it_through_the_command_line(tmp_path):
    """End to end through __main__, since that is what a deploy actually runs."""
    env_file = tmp_path / ".env.production"
    env_file.write_text("ENV=production\nMETRICS_TOKEN=placeholder\n")

    result = subprocess.run(
        ["python", "scripts/check_production_env.py", str(env_file)],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )

    assert "Alertmanager" in result.stdout, result.stdout[-500:]
    assert result.returncode == 1, "an unusable alerting config must block deploy"


def test_the_gate_only_runs_against_a_production_env_file(tmp_path):
    """The whole script is production-only: it fails on any ENV that is not
    production, so these checks can never affect a dev or staging run."""
    env_file = tmp_path / ".env.staging"
    env_file.write_text("ENV=staging\n")

    result = subprocess.run(
        ["python", "scripts/check_production_env.py", str(env_file)],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )

    assert "ENV must be 'production'" in result.stdout
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# 8 & 9. Nothing leaks, and no document recommends the mode that breaks delivery
# ---------------------------------------------------------------------------


def test_the_secret_files_can_never_be_committed(gate):
    """Asserted for every file the production config names, on every host."""
    config = yaml.safe_load(CONFIG.read_text())

    for reference in gate.alertmanager_secret_references(config):
        relative = "secrets/" + reference.split(MOUNT + "/", 1)[1]

        ignored = subprocess.run(
            ["git", "check-ignore", "-v", relative],
            capture_output=True, text=True, cwd=REPO, timeout=60,
        )

        assert ignored.returncode == 0, f"{relative} is not gitignored"
        assert "secrets/" in ignored.stdout


def test_no_tracked_file_contains_a_secret_value(gate):
    """Where the real files exist, prove their contents are nowhere in git."""
    config = yaml.safe_load(CONFIG.read_text())

    for reference in gate.alertmanager_secret_references(config):
        host = REPO / "secrets" / reference.split(MOUNT + "/", 1)[1]

        if not host.is_file():
            continue

        value = host.read_text().strip()

        if not value:
            continue

        hits = subprocess.run(
            ["git", "grep", "-lF", value],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )

        assert hits.stdout.strip() == "", (
            f"the contents of {host.name} appear in: {hits.stdout!r}"
        )


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_recommends_chmod_600_on_a_mounted_secret(doc):
    """Following that instruction is what produced the outage. It is acceptable
    ONLY when paired with a chown to the container's uid on the same line."""
    path = REPO / doc

    if not path.is_file():
        pytest.fail(f"{doc} does not exist")

    for raw in path.read_text().splitlines():
        if "chmod 600" not in raw or "secrets/" not in raw:
            continue

        # Only INSTRUCTION lines count. A command begins with the command, after
        # any comment/bullet/prompt marker; prose that names chmod 600 as the
        # failure mode -- which the docs now do deliberately -- does not.
        line = raw.strip().lstrip("#$-*` \t")

        if not line.startswith("chmod"):
            continue

        assert "chown" in raw, (
            f"{doc} instructs chmod 600 on a mounted secret without a chown, "
            f"which makes it unreadable to uid 65534: {raw.strip()!r}"
        )


def test_the_uid_is_recorded_once_rather_than_repeated(gate):
    """One constant, shared by the Prometheus and Alertmanager checks — both
    images run as the same user, and two copies would drift."""
    import ast

    assert gate.SECRET_READER_UID == 65534

    source = (REPO / "scripts" / "check_production_env.py").read_text()

    literals = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and node.value == 65534
    ]

    # Comments recording the measurement are fine and wanted; a second literal
    # in the CODE is the drift risk.
    assert len(literals) == 1, (
        f"the uid appears as a literal {len(literals)} times in code; every use "
        "should come from SECRET_READER_UID"
    )
