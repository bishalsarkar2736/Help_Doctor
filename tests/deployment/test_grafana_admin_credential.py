"""Grafana's admin password, checked before deploy rather than during an incident.

GF_SECURITY_ADMIN_PASSWORD comes from compose interpolation of
GRAFANA_ADMIN_PASSWORD. Unset, compose substitutes an empty string with a
warning nobody reads during a deploy, and Grafana starts with no usable admin
credential. Nothing fails: the container is healthy, Prometheus keeps scraping,
and the gap is found when someone needs a dashboard and cannot sign in.

It is also not recoverable through the interface — the container re-applies the
variable on every start, so a password set in the UI is overwritten.

Covered both ways, following the METRICS_TOKEN precedent: the check function
directly, and the gate as a deployer actually runs it.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MODULE_PATH = REPO / "scripts" / "check_production_env.py"

PASSWORD = "grafana-admin-value-9f3c1a"


@pytest.fixture
def checker(tmp_path, monkeypatch):
    """The script, loaded fresh so its module-level result lists start empty.

    sys.argv is pointed at a real file because check() re-reads the env file
    itself to find duplicate keys — under pytest, argv[1] is whatever the run
    was given, and pytest is usually given a directory. Same workaround as
    tests/deployment/test_alertmanager_secrets.py.
    """
    spec = importlib.util.spec_from_file_location(
        "check_prod_env_grafana_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    module.ERRORS.clear()
    module.WARNINGS.clear()
    module.OK.clear()

    env_file = tmp_path / ".env.production"
    env_file.write_text("ENV=production\n")
    monkeypatch.setattr(sys, "argv", ["check_production_env.py", str(env_file)])

    return module


def _run_gate(tmp_path, **overrides) -> subprocess.CompletedProcess:
    values = {
        "ENV": "production",
        "METRICS_TOKEN": "metrics-token-value",
        "GRAFANA_ADMIN_PASSWORD": PASSWORD,
    }
    values.update(overrides)

    env_file = tmp_path / ".env.production"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in values.items() if v is not None)
    )

    return subprocess.run(
        ["python", "scripts/check_production_env.py", str(env_file)],
        capture_output=True, text=True, cwd=REPO, timeout=120,
    )


# ---------------------------------------------------------------------------
# In-process
# ---------------------------------------------------------------------------


def test_a_set_password_passes(checker):
    checker.check({"ENV": "production", "GRAFANA_ADMIN_PASSWORD": PASSWORD})

    assert any("GRAFANA_ADMIN_PASSWORD set" in m for m in checker.OK)


def test_an_unset_password_is_refused(checker):
    checker.check({"ENV": "production"})

    assert any("GRAFANA_ADMIN_PASSWORD is unset" in m for m in checker.ERRORS)


def test_an_empty_password_is_refused(checker):
    """Exactly what compose substitutes when the variable is missing."""
    checker.check({"ENV": "production", "GRAFANA_ADMIN_PASSWORD": ""})

    assert any("GRAFANA_ADMIN_PASSWORD is unset" in m for m in checker.ERRORS)


def test_the_message_names_the_consequence(checker):
    """House style: the failure says what breaks, not which rule was violated."""
    checker.check({"ENV": "production"})

    message = next(m for m in checker.ERRORS if "GRAFANA_ADMIN_PASSWORD" in m)

    assert "cannot be signed into" in message


# ---------------------------------------------------------------------------
# Reuse
# ---------------------------------------------------------------------------


def test_a_password_reused_from_another_secret_is_refused(checker):
    """Grafana's admin reads every dashboard and datasource, and this value goes
    through compose rather than a mounted secret — sharing it widens whatever
    the other secret already exposes."""
    checker.check({
        "ENV": "production",
        "JWT_SECRET_KEY": "x" * 40,
        "GRAFANA_ADMIN_PASSWORD": "x" * 40,
    })

    assert any(
        "GRAFANA_ADMIN_PASSWORD reuses the same value" in m
        for m in checker.ERRORS
    )


def test_distinct_secrets_are_not_flagged(checker):
    checker.check({
        "ENV": "production",
        "JWT_SECRET_KEY": "a" * 40,
        "GRAFANA_ADMIN_PASSWORD": "b" * 40,
    })

    assert not any("reuses the same value" in m for m in checker.ERRORS)


# ---------------------------------------------------------------------------
# Subprocess — the gate as a deployer runs it
# ---------------------------------------------------------------------------


def test_the_gate_reports_a_missing_grafana_password(tmp_path):
    result = _run_gate(tmp_path, GRAFANA_ADMIN_PASSWORD=None)

    assert "GRAFANA_ADMIN_PASSWORD is unset" in result.stdout
    assert result.returncode == 1


def test_the_gate_accepts_a_set_grafana_password(tmp_path):
    result = _run_gate(tmp_path)

    assert "GRAFANA_ADMIN_PASSWORD set" in result.stdout


def test_the_gate_reports_a_reused_grafana_password(tmp_path):
    result = _run_gate(
        tmp_path, JWT_SECRET_KEY="z" * 40, GRAFANA_ADMIN_PASSWORD="z" * 40
    )

    assert "GRAFANA_ADMIN_PASSWORD reuses the same value" in result.stdout
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# The template offers it
# ---------------------------------------------------------------------------


def test_the_production_template_carries_the_variable():
    """A deployer filling in the template must be offered the key; the gate can
    only refuse what someone knew to look for."""
    text = (REPO / ".env.production.example").read_text()

    assert "GRAFANA_ADMIN_PASSWORD=" in text


def test_the_template_placeholder_is_distinct_from_the_metrics_token():
    """Sharing a placeholder invites filling both with one value, and only one
    of the two is in the reuse check."""
    lines = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in (REPO / ".env.production.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert lines["GRAFANA_ADMIN_PASSWORD"] != lines["METRICS_TOKEN"]
