"""The monitoring documentation matches the monitoring system.

WHY THIS EXISTS
docs/MONITORING.md drifted badly and nothing noticed. It documented 8 of 23
alert rules, and two of its statements had become the opposite of true:

    "Celery-owned metrics are not collected at all"
    "Celery is not scraped"

Both were written when only the `api` container was scraped. By the time they
were caught there were five scrape jobs, and `celery_worker_up`,
`celery_tasks_total` and `outbox_worker_heartbeat` all had series in Prometheus.
A stale gap list is worse than none: someone reading it mid-incident would
dismiss a real Celery signal as unavailable.

WHAT THIS PINS
That every rule and every scrape job is documented, and that the specific
retired claims cannot come back. It deliberately does not check prose quality --
only the facts that go stale when the system changes and the documentation does
not.
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent

DOC = REPO / "docs" / "MONITORING.md"
ALERTS = REPO / "alerts.yml"
PROMETHEUS = REPO / "prometheus.yml"

# Statements that were true once, became false, and misled. Each is a substring
# that must not reappear.
RETIRED_CLAIMS = [
    "Celery-owned metrics are not collected at all",
    "Celery is not scraped",
    "Only the `api` container is scraped",
    "Celery failures are invisible to alerting",
    "No HTTP status-code metric",
]


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text()


@pytest.fixture(scope="module")
def rules() -> list:
    return [
        entry
        for group in yaml.safe_load(ALERTS.read_text())["groups"]
        for entry in group.get("rules", [])
        if "alert" in entry
    ]


@pytest.fixture(scope="module")
def groups() -> list:
    return [group["name"] for group in yaml.safe_load(ALERTS.read_text())["groups"]]


@pytest.fixture(scope="module")
def jobs() -> dict:
    return {
        job["job_name"]: job["static_configs"][0]["targets"]
        for job in yaml.safe_load(PROMETHEUS.read_text())["scrape_configs"]
    }


# ---------------------------------------------------------------------------
# Every rule and job is documented
# ---------------------------------------------------------------------------


def test_every_alert_rule_is_documented(doc, rules):
    """The failure this replaces: 15 of 23 rules existed and were unmentioned,
    including every worker and alerting-pipeline rule."""
    missing = [entry["alert"] for entry in rules if f"`{entry['alert']}`" not in doc]

    assert not missing, f"undocumented alert rules: {missing}"


def test_the_documented_rule_count_matches_reality(doc, rules):
    """A count in prose goes stale silently; this makes it fail loudly."""
    assert f"{len(rules)} rules" in doc, (
        f"the doc does not state the current rule count ({len(rules)})"
    )


def test_every_rule_group_is_documented(doc, groups):
    missing = [name for name in groups if name not in doc]

    assert not missing, f"undocumented rule groups: {missing}"


def test_every_scrape_job_is_documented(doc, jobs):
    """A job nobody documents is a signal nobody knows they have."""
    missing = [name for name in jobs if name not in doc]

    assert not missing, f"undocumented scrape jobs: {missing}"


def test_every_scrape_target_is_documented(doc, jobs):
    """The target, not just the job name -- knowing where to curl is the point."""
    missing = [
        target for targets in jobs.values() for target in targets if target not in doc
    ]

    assert not missing, f"undocumented scrape targets: {missing}"


# ---------------------------------------------------------------------------
# The retired claims stay retired
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("claim", RETIRED_CLAIMS)
def test_a_false_claim_does_not_reappear(doc, claim):
    """These were all true when written. That is exactly why they are dangerous:
    they read as authoritative and were never re-checked."""
    assert claim not in doc, (
        f"docs/MONITORING.md repeats a claim that is no longer true: {claim!r}"
    )


def test_the_gaps_that_remain_are_still_real(jobs):
    """The other half of the same problem: a gap list must not keep entries that
    have been closed, and must not drop ones that are open. Both remaining
    entries are asserted against the configuration rather than trusted.
    """
    compose = (REPO / "docker-compose.yml").read_text()

    # No Postgres/Redis exporter -- still true.
    assert "postgres-exporter" not in compose
    assert "redis-exporter" not in compose

    # Latency still carries no route label -- still true.
    metrics = (REPO / "app" / "core" / "metrics.py").read_text()
    start = metrics.index("api_request_latency = Histogram(")
    definition = metrics[start:metrics.index(")", start)]

    assert "labelnames" not in definition, (
        "api_request_latency now has labels; the documented gap is closed and "
        "the doc should say so"
    )


def test_the_dead_mans_switch_limitation_is_documented(doc):
    """The single most important caveat for anyone relying on these alerts."""
    assert "dead-man" in doc or "dead man" in doc


# ---------------------------------------------------------------------------
# The verification recipe actually works
# ---------------------------------------------------------------------------


def test_the_verification_section_does_not_recommend_an_empty_metric(doc):
    """`login_attempts_total` is a labelled counter with no series until someone
    logs in, so using it to check that scraping works returns nothing and looks
    identical to a broken scrape. It was step 4 of the recipe for months."""
    recipe_start = doc.index("How to verify it is actually working")
    recipe = doc[recipe_start:doc.index("## ", recipe_start + 10)]

    for line in recipe.splitlines():
        if line.strip().startswith("#"):
            continue

        if "login_attempts_total" in line:
            assert "always exists" in recipe or "until someone logs in" in recipe, (
                "the recipe queries login_attempts_total without warning that it "
                "is empty until first use"
            )


def test_the_verification_section_covers_delivery(doc):
    """Firing is not delivering -- the distinction this project learned the hard
    way, twice."""
    assert "alertmanager_notifications_failed_total" in doc
