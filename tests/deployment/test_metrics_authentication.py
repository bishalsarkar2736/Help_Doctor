"""Production /metrics stays protected AND stays scrapeable.

THE FAILURE CHAIN, MEASURED BEFORE THIS WAS WRITTEN
Flipping the one variable that makes this deployment production fails three
times, each revealed only after fixing the last:

  1. ALLOWED_HOSTS absent from the env file -> Settings refuses to start. Loud,
     obvious, already covered by check_production_env.py.
  2. METRICS_TOKEN absent -> app/main.py answers /metrics with 404 under
     ENV=production. The fastapi target goes DOWN. SILENT: the API serves
     traffic perfectly while HighServerErrorRate, PaymentEndpointErrors,
     HighAPILatency and LoginFailureSpike all lose their data.
  3. METRICS_TOKEN present but Prometheus not given it -> 401. Also silent, and
     bearer_token_file was commented out with the secret mount absent, so this
     was the state the repository actually shipped.

Stage 1 fails closed. Stages 2 and 3 fail OPEN in the way that matters: nothing
breaks except the ability to know anything is broken.

WHAT IS NOT BEING FIXED
The 404 and the 401 are correct and stay. /metrics exposes queue depths, failure
counts and request paths, and it is reachable from the compose network. The fix
is to give the scraper the credential, never to remove the lock.

WHY TWO PROMETHEUS FILES
`promtool check config` exits 1 when bearer_token_file names a missing path, and
the token file is gitignored and generated per host. One shared config with the
directive always on would therefore break the check on every fresh clone and in
CI. alertmanager.production.yml already exists for exactly this reason.

These tests hold both halves at once: the endpoint is still locked, and the key
is where the scraper will look for it.
"""

import pathlib
import subprocess

import pytest

from app.config import Settings

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"
COMPOSE_STAGING = REPO / "docker-compose.staging.yml"
PROM_DEV = REPO / "prometheus.yml"
PROM_PROD = REPO / "prometheus.production.yml"
ENV_EXAMPLE = REPO / ".env.example"
GITIGNORE = REPO / ".gitignore"

# Where the token lives on each side of the mount.
SECRET_HOST = "./secrets"
SECRET_IN_PROMETHEUS = "/etc/prometheus/secrets/metrics_token"
SECRET_RELATIVE = "secrets/metrics_token"

TOKEN = "placeholder-token-not-a-real-secret"


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
def base() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]


@pytest.fixture(scope="module")
def staging() -> dict:
    return yaml.load(COMPOSE_STAGING.read_text(), Loader=_Loader)["services"]


def _jobs(path: pathlib.Path) -> dict:
    return {
        job["job_name"]: job
        for job in yaml.safe_load(path.read_text())["scrape_configs"]
    }


# ---------------------------------------------------------------------------
# 5. Prometheus references the credential correctly
# ---------------------------------------------------------------------------


def test_the_production_config_exists():
    assert PROM_PROD.is_file(), (
        "there is no authenticated scrape config, so production either exposes "
        "/metrics or loses monitoring"
    )


def test_the_fastapi_job_sends_a_bearer_token_in_production():
    """THE REGRESSION. Without this the target sits DOWN the moment ENV flips."""
    job = _jobs(PROM_PROD)["fastapi"]

    assert job.get("bearer_token_file") == SECRET_IN_PROMETHEUS, (
        f"the production fastapi job does not read {SECRET_IN_PROMETHEUS}; "
        f"got {job.get('bearer_token_file')!r}"
    )


def test_the_token_is_read_from_a_file_never_written_inline():
    """A literal `bearer_token` in a committed file is a published secret."""
    for path in (PROM_PROD, PROM_DEV):
        config = yaml.safe_load(path.read_text())

        for job in config["scrape_configs"]:
            assert "bearer_token" not in job, (
                f"{path.name}:{job['job_name']} carries a literal bearer_token"
            )
            assert "authorization" not in job, (
                f"{path.name}:{job['job_name']} carries inline authorization"
            )


def test_the_bearer_token_path_is_the_one_compose_mounts():
    """The two halves are written in different files; a path that disagrees
    produces a 401 that looks exactly like a wrong token."""
    volumes = yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]["prometheus"]["volumes"]

    mounted = [v for v in volumes if v.startswith(f"{SECRET_HOST}:")]

    assert mounted, f"prometheus does not mount {SECRET_HOST}"

    container_path = mounted[0].split(":")[1]

    assert SECRET_IN_PROMETHEUS.startswith(container_path + "/"), (
        f"bearer_token_file {SECRET_IN_PROMETHEUS} is not inside the mounted "
        f"directory {container_path}"
    )


def test_only_the_credential_differs_between_the_two_configs():
    """Two files is a drift risk; this is what makes it safe. A job added to one
    and not the other would silently go unmonitored in production only."""
    dev, prod = _jobs(PROM_DEV), _jobs(PROM_PROD)

    assert set(dev) == set(prod), (
        f"the configs scrape different jobs: dev={sorted(dev)} prod={sorted(prod)}"
    )

    for name in dev:
        stripped = {k: v for k, v in prod[name].items() if k != "bearer_token_file"}

        assert stripped == dev[name], (
            f"job {name!r} differs beyond the credential: "
            f"{stripped} != {dev[name]}"
        )


def test_both_configs_load_the_same_rules_and_alertmanager():
    dev = yaml.safe_load(PROM_DEV.read_text())
    prod = yaml.safe_load(PROM_PROD.read_text())

    assert dev["rule_files"] == prod["rule_files"]
    assert dev["alerting"] == prod["alerting"]
    assert dev["global"] == prod["global"]


def test_the_dev_config_stays_unauthenticated():
    """Development and staging have no token file; requiring one there would
    break `promtool check config` on every fresh clone."""
    assert "bearer_token_file" not in _jobs(PROM_DEV)["fastapi"]


# ---------------------------------------------------------------------------
# 6. Compose mounts the credential, read-only
# ---------------------------------------------------------------------------


def test_prometheus_mounts_the_secrets_directory_read_only(base):
    volumes = base["prometheus"]["volumes"]

    mounted = [v for v in volumes if v.startswith(f"{SECRET_HOST}:")]

    assert mounted, f"prometheus does not mount {SECRET_HOST}"
    assert mounted[0].endswith(":ro"), (
        f"the secret mount is writable: {mounted[0]!r}"
    )


def test_the_config_file_is_selectable_per_environment(base):
    """Same indirection alertmanager already uses, so production can point at
    the authenticated config without editing a tracked file."""
    volumes = base["prometheus"]["volumes"]

    config_mounts = [v for v in volumes if "/etc/prometheus/prometheus.yml" in v]

    assert config_mounts, "prometheus.yml is not mounted"
    assert "PROMETHEUS_CONFIG" in config_mounts[0], (
        f"the config path is hard-coded: {config_mounts[0]!r}"
    )
    assert ":ro" in config_mounts[0]


def test_the_default_config_is_the_development_one(base):
    """An unset PROMETHEUS_CONFIG must not break local work."""
    volumes = base["prometheus"]["volumes"]

    config_mount = next(v for v in volumes if "/etc/prometheus/prometheus.yml" in v)

    assert ":-./prometheus.yml}" in config_mount, (
        f"the default is not the dev config: {config_mount!r}"
    )


def test_the_secret_directory_matches_the_one_alertmanager_uses(base):
    """One gitignored directory for mounted secrets, not two conventions."""
    prometheus = [v for v in base["prometheus"]["volumes"] if v.startswith(SECRET_HOST)]
    alertmanager = [v for v in base["alertmanager"]["volumes"] if v.startswith(SECRET_HOST)]

    assert prometheus and alertmanager
    assert prometheus[0].split(":")[0] == alertmanager[0].split(":")[0]


# ---------------------------------------------------------------------------
# 3 & 4. The endpoint itself: locked without the token, open with it
# ---------------------------------------------------------------------------


@pytest.fixture
def token_configured(monkeypatch):
    """Turn the lock on for one test.

    The route closes over the module-level `settings` in app.main and reads
    METRICS_TOKEN per request, so setting the attribute is enough -- and it uses
    the suite's shared client, not a second one.

    Deliberately NOT a fastapi TestClient: that runs the app lifespan in its own
    event loop, leaving asyncpg connections pooled against a loop that is then
    closed. The next test to touch the database gets "attached to a different
    loop" -- measured, it broke test_schema_gate.py from this file.
    """
    import app.main

    monkeypatch.setattr(app.main.settings, "METRICS_TOKEN", TOKEN)


@pytest.mark.asyncio
async def test_metrics_without_a_token_is_rejected_when_a_token_is_configured(
    client, token_configured
):
    """Asserted against the real route rather than a restatement of it."""
    assert (await client.get("/metrics")).status_code == 401


@pytest.mark.asyncio
async def test_metrics_with_the_wrong_token_is_rejected(client, token_configured):
    response = await client.get("/metrics", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_metrics_with_the_correct_token_is_served(client, token_configured):
    response = await client.get(
        "/metrics", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert "# HELP" in response.text


@pytest.mark.asyncio
async def test_metrics_is_still_open_when_no_token_is_configured(client):
    """Development and staging are unchanged: no token, no lock."""
    assert (await client.get("/metrics")).status_code == 200


# ---------------------------------------------------------------------------
# 1 & 2. The deploy gate catches the half the env file cannot show
# ---------------------------------------------------------------------------


def _run_gate(tmp_path, **overrides) -> subprocess.CompletedProcess:
    values = {
        "ENV": "production",
        "METRICS_TOKEN": TOKEN,
    }
    values.update(overrides)

    env_file = tmp_path / ".env.production"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in values.items() if v is not None))

    return subprocess.run(
        ["python", "scripts/check_production_env.py", str(env_file)],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )


def test_the_gate_reports_a_missing_metrics_token(tmp_path):
    result = _run_gate(tmp_path, METRICS_TOKEN=None)

    assert "METRICS_TOKEN is unset" in result.stdout
    assert result.returncode == 1


def test_the_gate_reports_a_token_the_scraper_cannot_send(tmp_path):
    """The half that was invisible: token set, Prometheus still locked out.

    Skipped when a real secrets/metrics_token happens to exist and match, since
    the check would then correctly pass.
    """
    secret = REPO / SECRET_RELATIVE

    if secret.is_file() and secret.read_text() == TOKEN:
        pytest.skip("a matching token file exists on this host")

    result = _run_gate(tmp_path)

    assert "metrics_token" in result.stdout
    assert result.returncode == 1


def test_the_gate_rejects_a_secret_prometheus_cannot_read(tmp_path, monkeypatch):
    """The trap that cost a debugging round, kept as a test.

    prom/prometheus runs as nobody (65534). A 0600 token file owned by the
    deploying user -- the mode every instinct says to use for a secret, and the
    mode this repository's own docs used to recommend -- is UNREADABLE to it:

        unable to read authorization credentials: permission denied

    Measured: 600 DENIED, 640 DENIED, 644 READABLE. The failure looks exactly
    like a wrong token, and the target simply stays down.
    """
    import importlib

    gate = importlib.import_module("scripts.check_production_env")

    monkeypatch.setattr(gate, "REPO", tmp_path)

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    target = secrets_dir / "metrics_token"
    target.write_text(TOKEN)
    target.chmod(0o600)

    gate.ERRORS.clear()
    gate.WARNINGS.clear()
    gate.OK.clear()

    gate.check_metrics_scrape_credential({"METRICS_TOKEN": TOKEN})

    assert any("cannot read it" in e for e in gate.ERRORS), gate.ERRORS

    target.chmod(0o644)
    gate.ERRORS.clear()

    gate.check_metrics_scrape_credential({"METRICS_TOKEN": TOKEN})

    assert not any("cannot read it" in e for e in gate.ERRORS), gate.ERRORS


def test_no_documentation_tells_the_operator_to_chmod_600_the_token():
    """Structural guard on the instruction itself: following it breaks the
    scrape, and the wrong version of this line shipped in three files."""
    for name in (".env.example", "prometheus.yml", "prometheus.production.yml",
                 "docs/DEPLOYMENT.md", "docs/MONITORING.md", "docs/CONFIGURATION.md"):
        for line in (REPO / name).read_text().splitlines():
            if "chmod 600 secrets/metrics_token" not in line:
                continue

            # Legitimate only when the file is also handed to Prometheus's uid.
            assert "chown" in line, (
                f"{name} tells the operator to chmod 600 the token without a "
                f"chown, which makes it unreadable to Prometheus (uid 65534) "
                f"and fails every scrape: {line.strip()!r}"
            )


def test_the_gate_names_the_production_prometheus_config(tmp_path):
    """A deploy that forgets PROMETHEUS_CONFIG mounts the unauthenticated file
    and the target stays DOWN, so the gate has to say so."""
    result = _run_gate(tmp_path)

    assert "PROMETHEUS_CONFIG" in result.stdout


# ---------------------------------------------------------------------------
# 9. No secret value reaches a tracked file
# ---------------------------------------------------------------------------


def test_the_secrets_directory_is_gitignored():
    assert "secrets/" in GITIGNORE.read_text().splitlines()


def test_no_secret_file_is_tracked():
    tracked = subprocess.run(
        ["git", "ls-files", "secrets/"],
        capture_output=True, text=True, cwd=REPO, timeout=60,
    ).stdout.strip()

    assert tracked == "", f"secret files are tracked by git: {tracked!r}"


def test_the_example_env_carries_no_token_value():
    """The variable must be discoverable and empty."""
    line = next(
        raw for raw in ENV_EXAMPLE.read_text().splitlines()
        if raw.startswith("METRICS_TOKEN=")
    )

    assert line.split("=", 1)[1].strip() == "", f"a value is committed: {line!r}"


def test_the_token_file_can_never_be_committed():
    """The guarantee, asserted on every host rather than only where a token
    happens to exist.

    `git check-ignore` resolves the path against the ignore rules whether or not
    the file is there, so this runs in CI and on a fresh clone -- the earlier
    version of this test skipped everywhere except a machine that had already
    been configured for production, which is precisely where a leak check is
    least likely to be watched.

    When a real token IS present, the file's contents are scanned too, so the
    stronger check still happens where it can.
    """
    ignored = subprocess.run(
        ["git", "check-ignore", "-v", SECRET_RELATIVE],
        capture_output=True, text=True, cwd=REPO, timeout=60,
    )

    assert ignored.returncode == 0, (
        f"{SECRET_RELATIVE} is not gitignored — following the documented "
        "procedure would leave a real token stageable"
    )
    assert "secrets/" in ignored.stdout, (
        f"ignored by an unexpected rule: {ignored.stdout.strip()!r}"
    )

    secret = REPO / SECRET_RELATIVE
    value = secret.read_text().strip() if secret.is_file() else ""

    if not value:
        return

    hits = subprocess.run(
        ["git", "grep", "-lF", value],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )

    assert hits.stdout.strip() == "", f"the token appears in: {hits.stdout!r}"


def test_a_created_token_file_does_not_show_up_as_committable():
    """End-to-end on the actual working tree: write the file the documented
    procedure tells operators to write, and prove git will not offer it.

    Skipped rather than clobbered if a real token already exists.
    """
    secret = REPO / SECRET_RELATIVE

    if secret.exists():
        pytest.skip("a real token file exists here; not overwriting it")

    created_dir = not secret.parent.exists()
    secret.parent.mkdir(exist_ok=True)

    try:
        secret.write_text("sentinel-value-written-by-the-test-suite")

        porcelain = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, cwd=REPO, timeout=60,
        ).stdout

        assert SECRET_RELATIVE not in porcelain, (
            f"git offers the token file for commit:\n{porcelain}"
        )
    finally:
        secret.unlink(missing_ok=True)
        if created_dir:
            secret.parent.rmdir()


# ---------------------------------------------------------------------------
# 7 & 8. Staging and development keep working
# ---------------------------------------------------------------------------


def test_staging_does_not_override_the_prometheus_config(staging):
    """Staging inherits the base volumes and sets no PROMETHEUS_CONFIG, so it
    keeps the unauthenticated config it has always used."""
    assert set(staging["prometheus"]) <= {"container_name", "ports"}


def test_staging_and_development_need_no_token():
    """Neither refuses to start without METRICS_TOKEN."""
    for env in ("development", "staging"):
        settings = Settings(
            _env_file=None,
            ENV=env,
            POSTGRES_PASSWORD="placeholder",
            JWT_SECRET_KEY="x" * 40,
            MAIL_FROM="noreply@placeholder-mail-xyz.com",
            **{
                name: "https://gateway.placeholder-xyz.com" if "URL" in name else "placeholder"
                for name, field in Settings.model_fields.items()
                if field.is_required()
                and name not in {"POSTGRES_PASSWORD", "JWT_SECRET_KEY", "MAIL_FROM"}
            },
        )

        assert settings.METRICS_TOKEN is None


# ---------------------------------------------------------------------------
# 10 & 11. Nothing else moved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoints_are_unchanged(client):
    """Liveness only, deliberately.

    /health/ready runs the real database check, which opens the shared engine in
    the pytest-asyncio loop. scripts/verify_schema.py then calls asyncio.run()
    and finds those pooled connections "attached to a different loop" -- measured
    here: asserting readiness in this file failed
    test_schema_gate.py::test_it_passes_when_the_database_is_at_head purely by
    running before it. Readiness has its own coverage, with both checks stubbed,
    in tests/api/test_health_readiness.py.
    """
    live = await client.get("/health/live")

    assert live.status_code == 200
    assert live.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_trusted_host_behaviour_is_unchanged(client):
    """The /metrics path exemption and the rejection of everything else both
    survive this milestone."""
    assert (
        await client.get("/metrics", headers={"Host": "api:8000"})
    ).status_code == 200
    assert (
        await client.get("/health/live", headers={"Host": "api:8000"})
    ).status_code == 400
