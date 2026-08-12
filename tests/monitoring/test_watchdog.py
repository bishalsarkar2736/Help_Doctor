"""The dead-man's switch: an external signal that this system is still alive.

THE BLIND SPOT EVERY OTHER RULE SHARES
All 23 other rules in alerts.yml are evaluated BY Prometheus. If Prometheus
stops -- crashed, OOM-killed, host rebooted and the container never came back,
network partitioned -- every one of them stops evaluating at the same instant and
the stack goes perfectly silent. Silence is indistinguishable from health, and
nothing inside the stack can report it, because anything inside dies with it.

Even the alerting_pipeline rules cannot close this: they are evaluated by the
same Prometheus, and delivered by the same Alertmanager they are watching.

THE INVERSION
Watchdog fires permanently and is delivered continuously to an external monitor
(Healthchecks.io). That monitor alarms when the stream STOPS. Absence becomes the
alarm, and the alarm lives on infrastructure that does not share fate with this
host. That is the whole idea, and it is why no amount of in-repo cleverness can
substitute for the external endpoint.

WHAT THESE TESTS PIN
1. The rule fires with nothing to go on -- no series, no targets, t=0.
2. It is routed to the watchdog receiver EXCLUSIVELY. A permanently-firing alert
   reaching a human receiver would page someone every minute forever, which is
   how people learn to ignore pages.
3. Production reads the URL from a secret file, never inline: the URL is a
   credential -- whoever holds it can ping the monitor and silence the alarm.
4. The heartbeat is several times faster than the window it has to beat.

WHAT THEY DELIBERATELY DO NOT TEST
The external service. No test here needs a Healthchecks.io account, and none
should: the point of the endpoint is that it is outside this repository, this
host, and this test suite.
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

ALERTS = REPO / "alerts.yml"
DEV = REPO / "alertmanager.yml"
PROD = REPO / "alertmanager.production.yml"
RULE_TESTS = pathlib.Path(__file__).parent / "alerts_test.yml"

ALERT = "Watchdog"
SEVERITY = "watchdog"
RECEIVER = "watchdog"

SECRET = "/etc/alertmanager/secrets/watchdog_url"

# Healthchecks.io grace periods are set per check; the smallest sensible one is
# a few minutes. The heartbeat must be comfortably faster than that or an
# ordinary scheduling delay raises a false alarm.
INTENDED_EXTERNAL_TIMEOUT_SECONDS = 300

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _seconds(duration: str) -> int:
    return int(duration[:-1]) * UNITS[duration[-1]]


@pytest.fixture(scope="module")
def rule() -> dict:
    for group in yaml.safe_load(ALERTS.read_text())["groups"]:
        for entry in group.get("rules", []):
            if entry.get("alert") == ALERT:
                return entry

    raise AssertionError(f"{ALERT} is not defined in alerts.yml")


@pytest.fixture(scope="module")
def dev() -> dict:
    return yaml.safe_load(DEV.read_text())


@pytest.fixture(scope="module")
def prod() -> dict:
    return yaml.safe_load(PROD.read_text())


def _watchdog_route(config: dict) -> dict:
    for route in config["route"].get("routes", []):
        if any(SEVERITY in matcher for matcher in route.get("matchers", [])):
            return route

    raise AssertionError("no route matches severity=watchdog")


def _receiver(config: dict, name: str) -> dict:
    for entry in config["receivers"]:
        if entry["name"] == name:
            return entry

    raise AssertionError(f"no receiver named {name!r}")


# ---------------------------------------------------------------------------
# The rule fires with nothing to go on
# ---------------------------------------------------------------------------


def test_the_watchdog_rule_exists(rule):
    assert rule["alert"] == ALERT


def test_it_depends_on_no_metric(rule):
    """`vector(1)` is true against a completely empty TSDB -- the state after a
    restart, after data loss, and on a brand-new deployment. A watchdog built on
    any real metric would go quiet exactly when that metric stopped, which is
    when it is most needed."""
    expression = " ".join(rule["expr"].split())

    assert expression == "vector(1)", expression


def test_it_fires_immediately(rule):
    """A heartbeat with a pending period leaves a gap on every restart, and the
    external monitor cannot tell that gap from a dead host."""
    assert rule["for"] == "0m"


def test_it_carries_its_own_severity(rule):
    """Routing depends on this label, and it must not collide with a severity a
    human receiver subscribes to."""
    assert rule["labels"]["severity"] == SEVERITY
    assert rule["labels"]["severity"] not in ("critical", "warning", "info")


def test_it_lives_in_its_own_group():
    """Isolated so a rule-evaluation problem elsewhere in the file cannot delay
    the heartbeat, and so it is obvious this rule is not like the others."""
    groups = {
        group["name"]: [entry.get("alert") for entry in group.get("rules", [])]
        for group in yaml.safe_load(ALERTS.read_text())["groups"]
    }

    assert SEVERITY in groups, "there is no dedicated watchdog group"
    assert groups[SEVERITY] == [ALERT]


def test_no_other_rule_uses_the_watchdog_severity():
    """If a real alert were labelled watchdog it would be routed to the monitor
    and never reach a human."""
    offenders = [
        entry["alert"]
        for group in yaml.safe_load(ALERTS.read_text())["groups"]
        for entry in group.get("rules", [])
        if entry.get("labels", {}).get("severity") == SEVERITY and entry["alert"] != ALERT
    ]

    assert not offenders, f"these would be swallowed by the watchdog route: {offenders}"


def test_the_rule_tests_prove_it_fires_with_no_series():
    """The property that matters, asserted in promtool rather than inferred."""
    config = yaml.safe_load(RULE_TESTS.read_text())

    cases = [
        case
        for test in config["tests"]
        if test.get("input_series") == []
        for case in test.get("alert_rule_test", [])
        if case.get("alertname") == ALERT
    ]

    assert cases, "no promtool case runs the watchdog with an empty TSDB"
    assert any(case["eval_time"] == "0m" for case in cases), (
        "no promtool case checks the very first evaluation"
    )
    assert all(case.get("exp_alerts") for case in cases), (
        "a case expects the watchdog NOT to fire"
    )


# ---------------------------------------------------------------------------
# It is routed exclusively to the watchdog receiver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_a_dedicated_route_matches_the_watchdog(config, dev, prod):
    parsed = dev if config == "dev" else prod

    route = _watchdog_route(parsed)

    assert route["receiver"] == RECEIVER


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_route_does_not_continue(config, dev, prod):
    """THE ONE THAT MATTERS MOST. `continue: true` would let a permanently-firing
    alert fall through to the on-call receivers and page someone every minute,
    forever. The default is false; this asserts nobody has set it."""
    parsed = dev if config == "dev" else prod

    assert _watchdog_route(parsed).get("continue", False) is False


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_watchdog_route_is_first(config, dev, prod):
    """Alertmanager takes the first matching route. Ordering it first means no
    later rule can claim the heartbeat by accident."""
    parsed = dev if config == "dev" else prod

    routes = parsed["route"]["routes"]

    assert any(SEVERITY in m for m in routes[0].get("matchers", [])), (
        f"the watchdog route is not first: {routes[0].get('matchers')}"
    )


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_watchdog_never_reaches_a_human_receiver(config, dev, prod):
    """The receiver it routes to must carry no email and no chat integration."""
    parsed = dev if config == "dev" else prod

    receiver = _receiver(parsed, RECEIVER)

    for human in ("email_configs", "slack_configs", "pagerduty_configs",
                  "opsgenie_configs", "telegram_configs", "msteams_configs"):
        assert human not in receiver, (
            f"the watchdog receiver has {human}; a permanently-firing alert "
            "would notify a person every minute forever"
        )


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_default_receiver_is_not_the_watchdog(config, dev, prod):
    """If the watchdog route were ever removed, the alert would fall through to
    the default receiver. That is the failure this pairs with -- it must at
    least not be the default already."""
    parsed = dev if config == "dev" else prod

    assert parsed["route"]["receiver"] != RECEIVER


def test_the_human_receivers_are_unchanged(dev, prod):
    """This milestone adds a receiver; it must not have altered the ones that
    wake people up."""
    assert [r["name"] for r in dev["receivers"]] == ["default", "critical", RECEIVER]
    assert [r["name"] for r in prod["receivers"]] == [
        "oncall-email", "oncall-critical", RECEIVER
    ]


# ---------------------------------------------------------------------------
# Production delivers, via a secret file
# ---------------------------------------------------------------------------


def test_production_delivers_by_webhook(prod):
    receiver = _receiver(prod, RECEIVER)

    assert receiver.get("webhook_configs"), (
        "production's watchdog receiver sends nothing; the external monitor "
        "would see no heartbeat and alarm permanently"
    )


def test_production_reads_the_url_from_a_secret_file(prod):
    """The URL is a credential: anyone holding it can ping the monitor and
    suppress the alarm. This file is committed, so it must never appear here."""
    config = _receiver(prod, RECEIVER)["webhook_configs"][0]

    assert config.get("url_file") == SECRET, config
    assert "url" not in config, (
        "an inline URL in a committed file is a published credential"
    )


def test_no_real_heartbeat_url_is_committed():
    """Nothing in the repository may contain a usable Healthchecks.io ping URL.
    Checked across the configs and docs, not just the one file."""
    for path in (ALERTS, DEV, PROD, REPO / "docs" / "MONITORING.md",
                 REPO / "docs" / "DEPLOYMENT.md"):
        if not path.is_file():
            continue

        text = path.read_text()

        assert "hc-ping.com/" not in text or "<" in text, (
            f"{path.name} may contain a real Healthchecks.io URL"
        )

        for line in text.splitlines():
            if "hc-ping.com" not in line:
                continue

            # A placeholder is fine; a UUID-shaped path is not.
            import re

            assert not re.search(
                r"hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}", line
            ), f"{path.name} contains what looks like a real ping URL: {line.strip()}"


def test_the_secret_is_not_in_the_repository():
    """It is created at deploy time. Its absence here is the correct state."""
    assert not (REPO / "secrets" / "watchdog_url").exists(), (
        "a watchdog URL exists in the working tree; it must be created on the "
        "deploy host only"
    )


def test_the_deploy_gate_derives_the_watchdog_secret():
    """No bespoke validation was added: check_production_env.py already collects
    every *_file value from alertmanager.production.yml, so adding this receiver
    extended the gate automatically. This asserts that still holds."""
    import sys

    sys.path.insert(0, str(REPO))

    from scripts.check_production_env import alertmanager_secret_references

    references = alertmanager_secret_references(yaml.safe_load(PROD.read_text()))

    assert SECRET in references, (
        "the deploy gate no longer requires the watchdog URL; a deployment "
        "could ship with a dead switch"
    )


# ---------------------------------------------------------------------------
# The heartbeat outpaces the window it has to beat
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_heartbeat_is_faster_than_the_external_timeout(config, dev, prod):
    """If repeat_interval approached the monitor's grace period, an ordinary
    delay would raise a false alarm and the switch would be muted within a
    week."""
    parsed = dev if config == "dev" else prod

    repeat = _seconds(_watchdog_route(parsed)["repeat_interval"])

    assert repeat * 2 <= INTENDED_EXTERNAL_TIMEOUT_SECONDS, (
        f"repeat_interval is {repeat}s against an intended {INTENDED_EXTERNAL_TIMEOUT_SECONDS}s "
        "timeout; leave room for at least one missed ping"
    )


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_heartbeat_is_not_batched(config, dev, prod):
    """group_wait delays the first notification of a group. For a heartbeat that
    is pure latency before the monitor hears anything."""
    parsed = dev if config == "dev" else prod

    assert _seconds(_watchdog_route(parsed)["group_wait"]) == 0


@pytest.mark.parametrize("config", ["dev", "prod"])
def test_the_watchdog_repeats_faster_than_real_alerts(config, dev, prod):
    """Sanity: the heartbeat must be the most frequent thing in the file, or it
    is not a heartbeat."""
    parsed = dev if config == "dev" else prod

    watchdog = _seconds(_watchdog_route(parsed)["repeat_interval"])
    default = _seconds(parsed["route"]["repeat_interval"])

    assert watchdog < default
