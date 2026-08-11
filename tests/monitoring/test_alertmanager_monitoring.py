"""Alert delivery failures are detected.

WHAT WAS UNMONITORED, MEASURED ON THE RUNNING DEPLOYMENT
Every other rule in alerts.yml assumes a firing alert reaches a human. Nothing
checked that assumption, and it was false:

    alertmanager_alerts_received_total{status="firing"}              34
    alertmanager_notifications_total{integration="webhook"}          10
    alertmanager_notifications_failed_total{...,reason="clientError"} 10

Ten of ten notifications failed with `unexpected status code 404`, among them
CeleryWorkerDown and OutboxWorkerDown -- real alerts about background workers,
fired correctly and delivered to nobody.

WHY NOTHING NOTICED
`alerting.alertmanagers` in prometheus.yml is Prometheus SENDING alerts to
Alertmanager. It says nothing about whether Alertmanager then delivered them,
and Prometheus reported zero send errors throughout. The failure is on the last
hop, and there was no scrape job collecting Alertmanager's own metrics -- so the
one counter that recorded it was never read.

TWO HOPS, AND ONLY ONE WAS BLIND
Prometheus -> Alertmanager was already observable through
prometheus_notifications_errors_total on the existing `prometheus` job.
Alertmanager -> receiver is what this adds.

THE LIMIT, STATED HONESTLY
An alert about broken delivery is delivered by the thing it reports broken.
These rules make the failure visible in the Prometheus UI, in Grafana and in the
firing history -- where it was invisible before -- but they cannot page through a
path that is down. Closing that needs a dead-man's-switch routed to an external
service, which is a separate milestone.
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

ALERTS = REPO / "alerts.yml"
PROM_DEV = REPO / "prometheus.yml"
PROM_PROD = REPO / "prometheus.production.yml"
RULE_TESTS = pathlib.Path(__file__).parent / "alerts_test.yml"

JOB = "alertmanager"
TARGET = "alertmanager:9093"

DELIVERY_ALERT = "AlertmanagerNotificationsFailing"
DOWN_ALERT = "AlertmanagerDown"
RELOAD_ALERT = "AlertmanagerConfigReloadFailed"


@pytest.fixture(scope="module")
def rules() -> dict:
    return {
        entry["alert"]: entry
        for group in yaml.safe_load(ALERTS.read_text())["groups"]
        for entry in group.get("rules", [])
        if "alert" in entry
    }


def _jobs(path: pathlib.Path) -> dict:
    return {
        job["job_name"]: job
        for job in yaml.safe_load(path.read_text())["scrape_configs"]
    }


def _expr(rules: dict, name: str) -> str:
    assert name in rules, f"{name} is not defined in alerts.yml"

    return " ".join(rules[name]["expr"].split())


# ---------------------------------------------------------------------------
# Alertmanager is scraped at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("config", [PROM_DEV, PROM_PROD], ids=lambda p: p.name)
def test_alertmanager_is_scraped(config):
    """THE REGRESSION. Without this job the delivery counters exist and nothing
    reads them, which is exactly how 10 failed notifications went unnoticed."""
    jobs = _jobs(config)

    assert JOB in jobs, (
        f"{config.name} does not scrape Alertmanager; notification failures "
        "are recorded by Alertmanager and read by nobody"
    )
    assert jobs[JOB]["static_configs"][0]["targets"] == [TARGET]


def test_the_scrape_job_needs_no_credential():
    """Alertmanager has no authentication and is published only on loopback, so
    unlike the fastapi job this one is identical in both configs. If that ever
    changes, the production config needs a credential and this test should fail
    rather than the scrape silently 401ing."""
    assert "bearer_token_file" not in _jobs(PROM_PROD)[JOB]
    assert "authorization" not in _jobs(PROM_PROD)[JOB]


def test_the_job_is_identical_in_both_configs():
    """A job present in development only would leave production -- the one that
    matters -- unmonitored."""
    assert _jobs(PROM_DEV)[JOB] == _jobs(PROM_PROD)[JOB]


def test_sending_alerts_and_scraping_alertmanager_are_different_things():
    """`alerting.alertmanagers` was already configured and proves nothing about
    delivery: Prometheus reported zero send errors while every notification
    failed. Both must be present."""
    for config in (PROM_DEV, PROM_PROD):
        parsed = yaml.safe_load(config.read_text())

        targets = parsed["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]

        assert targets == [TARGET], f"{config.name} does not send alerts to {TARGET}"
        assert JOB in _jobs(config), f"{config.name} sends but does not scrape"


# ---------------------------------------------------------------------------
# The rules say what they need to say
# ---------------------------------------------------------------------------


def test_a_delivery_failure_rule_exists(rules):
    expression = _expr(rules, DELIVERY_ALERT)

    assert "alertmanager_notifications_failed_total" in expression
    assert f'job="{JOB}"' in expression


def test_the_delivery_rule_reports_which_integration_is_broken(rules):
    """`by (integration)` so the page names the broken path -- email, webhook,
    slack -- instead of only that something is broken."""
    expression = _expr(rules, DELIVERY_ALERT)

    assert "by (integration)" in expression.replace("by(", "by ("), expression
    assert "{{ $labels.integration }}" in rules[DELIVERY_ALERT]["annotations"]["summary"]


def test_the_delivery_rule_uses_a_rate_not_a_raw_counter(rules):
    """A counter is monotonic: `alertmanager_notifications_failed_total > 0`
    would latch on the first failure ever and never clear, so it would be
    ignored within a week."""
    expression = _expr(rules, DELIVERY_ALERT)

    assert "rate(" in expression or "increase(" in expression, expression


def test_the_delivery_rule_is_critical_and_waits_out_a_blip(rules):
    """Alertmanager retries; a transient 5xx recovers on its own. An
    unrecoverable clientError does not."""
    rule = rules[DELIVERY_ALERT]

    assert rule["labels"]["severity"] == "critical"
    assert rule["for"] == "10m"


def test_a_down_rule_exists_and_covers_a_missing_job(rules):
    """The lesson from NoTrafficReceived, applied here: if the scrape job is
    deleted or renamed there is no up{job="alertmanager"} series at all, and an
    empty vector compared to 0 is still empty -- the rule watching the alerting
    pipeline would itself go quiet."""
    expression = _expr(rules, DOWN_ALERT)

    assert f'up{{job="{JOB}"}} == 0' in expression
    assert f'absent(up{{job="{JOB}"}})' in expression, (
        "a deleted scrape job would silently disable this alert"
    )


def test_a_config_reload_rule_exists(rules):
    """A rejected reload keeps the PREVIOUS config running, so the deploy looks
    successful and the change silently did not happen."""
    expression = _expr(rules, RELOAD_ALERT)

    assert "alertmanager_config_last_reload_successful" in expression
    assert "== 0" in expression


@pytest.mark.parametrize("name", [DELIVERY_ALERT, DOWN_ALERT, RELOAD_ALERT])
def test_every_new_rule_explains_itself(rules, name):
    """These fire at 3am into a situation where the alerting system itself is
    suspect; a bare summary is not enough."""
    annotations = rules[name]["annotations"]

    assert annotations["summary"]
    assert len(annotations["description"]) > 80


def test_the_new_rules_live_in_their_own_group():
    """Grouped separately so an evaluation problem in the alerting-pipeline
    rules cannot delay the application rules, and vice versa."""
    groups = {
        group["name"]: [entry.get("alert") for entry in group.get("rules", [])]
        for group in yaml.safe_load(ALERTS.read_text())["groups"]
    }

    assert "alerting_pipeline" in groups

    assert set(groups["alerting_pipeline"]) == {
        DELIVERY_ALERT, DOWN_ALERT, RELOAD_ALERT
    }


def test_the_known_limitation_is_recorded():
    """The circularity is the single most important thing for whoever reads
    these rules during an incident: this alert cannot page through a delivery
    path that is broken."""
    text = ALERTS.read_text()

    assert "dead-man" in text or "dead man" in text, (
        "the limitation of alerting on your own alerting is not recorded"
    )


# ---------------------------------------------------------------------------
# The behaviour is proven, not just the shape
# ---------------------------------------------------------------------------


def test_the_rule_tests_cover_every_new_alert():
    """Each rule must have a promtool case that makes it FIRE. A rule that has
    only ever been parsed is the thing this milestone exists to stop."""
    config = yaml.safe_load(RULE_TESTS.read_text())

    fired = {
        case["alertname"]
        for test in config["tests"]
        for case in test.get("alert_rule_test", [])
        if case.get("exp_alerts")
    }

    for name in (DELIVERY_ALERT, DOWN_ALERT, RELOAD_ALERT):
        assert name in fired, f"no promtool case proves {name} fires"


def test_the_rule_tests_cover_the_quiet_cases_too():
    """A rule that fires on everything is as useless as one that never fires."""
    config = yaml.safe_load(RULE_TESTS.read_text())

    silent = {
        case["alertname"]
        for test in config["tests"]
        for case in test.get("alert_rule_test", [])
        if case.get("exp_alerts") == []
    }

    for name in (DELIVERY_ALERT, DOWN_ALERT):
        assert name in silent, f"no promtool case proves {name} stays quiet"


def test_the_missing_job_case_is_covered():
    names = [
        test.get("name", "")
        for test in yaml.safe_load(RULE_TESTS.read_text())["tests"]
    ]

    assert any("missing alertmanager scrape job" in name for name in names), names
