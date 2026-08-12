"""Development alert delivery actually delivers.

WHAT WAS BROKEN
Both dev receivers were `webhook_configs` posting alert JSON to
http://mailhog:8025/api/v2/messages. Every notification failed:

    unexpected status code 404: 404 page not found

Measured on this deployment: 10 attempts, 10 failures, among them
CeleryWorkerDown and OutboxWorkerDown. Development alerting had never worked.

WHY NO URL COULD HAVE FIXED IT
Port 8025 is MailHog's READ api and web UI. It has no ingest endpoint, and
answers 404 to POST on every path -- /api/v2/messages, /api/v1/messages, / and
/webhook alike. MailHog catches MAIL, on port 1025. The receiver type was wrong,
not the address.

TWO SETTINGS THAT LOOK OPTIONAL AND ARE NOT
`smtp_require_tls: false` is required: MailHog's EHLO advertises only `auth` and
`pipelining`, so Alertmanager's default of true fails every send with
"'require_tls' is true (default) but the server does not advertise STARTTLS".
Measured: 0 delivered without it, 1 with it.

No credentials, equally deliberate. MailHog advertises `auth`, so adding
smtp_auth_username/password looks like hardening -- and breaks delivery with
"*smtp.plainAuth auth: unencrypted connection", because Go's SMTP client refuses
PLAIN over an unencrypted link. Measured: 0 delivered. Both are pinned below,
because both are the kind of thing a well-meaning later edit re-breaks.

SCOPE
Development only. alertmanager.production.yml keeps smtp_require_tls: true, a
real smarthost and a mounted credential file; tests here assert this milestone
did not touch it.
"""

import pathlib
import shutil
import subprocess

import pytest

# Derived from docker-compose.yml: amtool is a schema validator, so it must
# be the version the server runs. Measured before this -- a check-config on
# v0.28.1 while 0.33.1 was deployed, five minors apart.
from tests.monitoring.monitoring_images import ALERTMANAGER_IMAGE

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

DEV = REPO / "alertmanager.yml"
PROD = REPO / "alertmanager.production.yml"

MAILHOG_SMTP = "mailhog:1025"
MAILHOG_HTTP_PORT = "8025"

CREDENTIAL_KEYS = [
    "smtp_auth_username",
    "smtp_auth_password",
    "smtp_auth_password_file",
    "smtp_auth_secret",
    "smtp_auth_identity",
]

docker_available = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker is not available in this environment",
)


@pytest.fixture(scope="module")
def dev() -> dict:
    return yaml.safe_load(DEV.read_text())


@pytest.fixture(scope="module")
def prod() -> dict:
    return yaml.safe_load(PROD.read_text())


def _configs(parsed: dict, kind: str) -> list:
    return [
        config
        for receiver in parsed["receivers"]
        for config in receiver.get(kind, [])
    ]


# ---------------------------------------------------------------------------
# The dev config delivers by SMTP to MailHog
# ---------------------------------------------------------------------------


# The dead-man's switch terminates in a receiver with no delivery configured at
# all (see alertmanager.yml). It is not a human receiver and these rules about
# SMTP delivery do not apply to it.
WATCHDOG_RECEIVER = "watchdog"


def _human_receivers(parsed: dict) -> list:
    return [r for r in parsed["receivers"] if r["name"] != WATCHDOG_RECEIVER]


def test_the_dev_receivers_use_email_not_webhook(dev):
    """THE REGRESSION. A webhook receiver against MailHog can only ever 404."""
    for receiver in _human_receivers(dev):
        assert "email_configs" in receiver, (
            f"receiver {receiver['name']!r} does not deliver by SMTP"
        )
        assert "webhook_configs" not in receiver, (
            f"receiver {receiver['name']!r} still posts a webhook to MailHog, "
            "which has no ingest endpoint and answers 404 to every POST"
        )


def test_no_receiver_posts_to_the_mailhog_http_api(dev):
    """Guards the specific mistake, in any receiver type, at any path."""
    text = DEV.read_text()

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("#"):
            continue

        assert f"mailhog:{MAILHOG_HTTP_PORT}" not in stripped, (
            f"a receiver targets MailHog's read API, which cannot accept "
            f"deliveries: {stripped!r}"
        )


def test_the_smarthost_is_mailhogs_smtp_port(dev):
    assert dev["global"]["smtp_smarthost"] == MAILHOG_SMTP


def test_a_sender_address_is_configured(dev):
    """Alertmanager refuses to send without one."""
    assert dev["global"]["smtp_from"] == "alerts@helpdoctor.local"


def test_tls_is_not_required_against_mailhog(dev):
    """MailHog advertises no STARTTLS. With the default of true, every send
    fails and nothing is delivered -- measured."""
    assert dev["global"]["smtp_require_tls"] is False


# ---------------------------------------------------------------------------
# No credentials, deliberately
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", CREDENTIAL_KEYS)
def test_the_dev_config_carries_no_smtp_credentials(dev, key):
    """Adding credentials looks like hardening and breaks delivery: Go's SMTP
    client refuses PLAIN auth over an unencrypted connection."""
    assert key not in dev["global"], (
        f"{key} is set for MailHog; delivery then fails with "
        '"*smtp.plainAuth auth: unencrypted connection"'
    )


def test_no_receiver_carries_inline_credentials(dev):
    """A committed credential is a published credential, whatever it is for."""
    for config in _configs(dev, "email_configs"):
        for key in ("auth_username", "auth_password", "auth_secret"):
            assert key not in config, f"{key} is inline in a dev receiver"


def test_the_dev_config_reads_no_secret_files(dev):
    """Development must start on a fresh clone, where ./secrets is empty."""
    text = DEV.read_text()

    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue

        assert "_file:" not in line, (
            f"the dev config reads a mounted secret, so a fresh clone cannot "
            f"start it: {line.strip()!r}"
        )


# ---------------------------------------------------------------------------
# Routing behaviour is untouched
# ---------------------------------------------------------------------------


def test_routing_and_inhibition_are_unchanged(dev):
    """This milestone changes HOW a notification is delivered, not who gets it
    or when."""
    route = dev["route"]

    assert route["group_by"] == ["alertname", "severity"]
    assert route["group_wait"] == "30s"
    assert route["group_interval"] == "5m"
    assert route["repeat_interval"] == "4h"
    assert route["receiver"] == "default"

    # By receiver, not by index -- the watchdog route is deliberately first so
    # nothing else can claim the heartbeat.
    critical = next(r for r in route["routes"] if r["receiver"] == "critical")

    assert critical["receiver"] == "critical"
    assert critical["group_wait"] == "10s"
    assert critical["repeat_interval"] == "1h"

    inhibit = dev["inhibit_rules"][0]

    assert inhibit["source_matchers"] == ['alertname = "APIDown"']
    assert inhibit["target_matchers"] == ['severity = "warning"']
    assert inhibit["equal"] == ["job"]


def test_both_human_receivers_still_exist(dev):
    """The watchdog receiver was added alongside them, not instead of them."""
    assert [r["name"] for r in _human_receivers(dev)] == ["default", "critical"]
    assert WATCHDOG_RECEIVER in [r["name"] for r in dev["receivers"]]


def test_resolved_notifications_are_still_sent(dev):
    """Losing this would leave a resolved incident looking open forever."""
    configs = [
        config
        for receiver in _human_receivers(dev)
        for config in receiver.get("email_configs", [])
    ]

    assert configs, "no email receivers"
    assert all(config["send_resolved"] is True for config in configs)


# ---------------------------------------------------------------------------
# Production is not touched
# ---------------------------------------------------------------------------


def test_production_still_requires_tls(prod):
    """The dev relaxation must not leak into the config that talks to a real
    mail server."""
    assert prod["global"]["smtp_require_tls"] is True


def test_production_still_uses_a_real_smarthost(prod):
    assert prod["global"]["smtp_smarthost"] != MAILHOG_SMTP
    assert "mailhog" not in prod["global"]["smtp_smarthost"]


def test_production_still_authenticates_from_a_secret_file(prod):
    assert prod["global"]["smtp_auth_password_file"].startswith(
        "/etc/alertmanager/secrets/"
    )
    assert "smtp_auth_password" not in prod["global"], "an inline password"


def test_production_keeps_its_second_channel(prod):
    """Email is the one that gets filtered and read in the morning; the Slack
    receiver is why a critical alert makes a sound."""
    slack = _configs(prod, "slack_configs")

    assert slack, "the critical receiver lost its Slack channel"
    assert slack[0]["api_url_file"].startswith("/etc/alertmanager/secrets/")


def test_the_dev_settings_never_reach_production(prod):
    """The property this replaces a git-diff check with.

    This started as "production is byte-identical to HEAD", which was true for
    the milestone that wrote it and is now wrong twice over: the dead-man's
    switch legitimately adds a receiver to production, and once committed the
    comparison passes trivially against itself. What actually matters is that
    development's two deliberate relaxations never appear in the config that
    talks to a real mail server.
    """
    settings = prod["global"]

    assert settings["smtp_require_tls"] is True, (
        "production inherited development's TLS relaxation"
    )
    assert settings["smtp_smarthost"] != MAILHOG_SMTP
    assert "mailhog" not in settings["smtp_smarthost"]

    # Development has no credentials on purpose; production must have them, and
    # from a mounted file rather than inline.
    assert settings["smtp_auth_password_file"].startswith("/etc/alertmanager/secrets/")
    assert "smtp_auth_password" not in settings

    for receiver in _human_receivers(prod):
        for config in receiver.get("email_configs", []):
            assert "helpdoctor.local" not in config["to"], (
                f"{receiver['name']} still points at the development address"
            )


# ---------------------------------------------------------------------------
# The config is valid to Alertmanager itself
# ---------------------------------------------------------------------------


@docker_available
@pytest.mark.parametrize("config", [DEV, PROD], ids=lambda p: p.name)
def test_amtool_accepts_the_config(config):
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{config}:/c.yml:ro",
            "--entrypoint", "amtool", ALERTMANAGER_IMAGE,
            "check-config", "/c.yml",
        ],
        capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0 and "Unable to find image" in result.stderr:
        pytest.skip("alertmanager image is not available locally")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SUCCESS" in result.stdout
