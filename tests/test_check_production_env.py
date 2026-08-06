"""The database half of the production environment check.

The application refuses to start on a contradictory database configuration, but
that is discovered when the container is already rolling. This check runs
against the env file before anything is deployed, so the same mistake is caught
while it still costs nothing.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_production_env.py"
)


@pytest.fixture
def checker():
    """The script, loaded fresh so its module-level result lists start empty."""
    spec = importlib.util.spec_from_file_location(
        "check_production_env_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    module.ERRORS.clear()
    module.WARNINGS.clear()
    module.OK.clear()

    return module


AGREEING = {
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "helpdoctor",
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "secret$pass",
    "DATABASE_URL": "postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor",
}


def test_agreeing_configuration_passes(checker):
    checker.check_database_target(dict(AGREEING))

    assert checker.ERRORS == []
    assert any("agrees" in line for line in checker.OK)


def test_a_different_database_is_an_error(checker):
    env = dict(AGREEING)
    env["DATABASE_URL"] = "postgresql+asyncpg://app:secret%24pass@db:5432/other"

    checker.check_database_target(env)

    assert checker.ERRORS
    assert "database" in checker.ERRORS[0]


def test_a_different_host_is_an_error(checker):
    """The shape of a half-finished move to a managed database."""
    env = dict(AGREEING)
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://app:secret%24pass@rds.example.com:5432/helpdoctor"
    )

    checker.check_database_target(env)

    assert checker.ERRORS


def test_a_rotated_password_in_one_place_is_an_error(checker):
    """Rotating the credential in the parts and not the URL, or the reverse."""
    env = dict(AGREEING)
    env["POSTGRES_PASSWORD"] = "new$pass"

    checker.check_database_target(env)

    assert checker.ERRORS
    assert "password" in checker.ERRORS[0]


def test_the_password_value_is_not_printed(checker):
    """This runs in deploy output."""
    env = dict(AGREEING)
    env["POSTGRES_PASSWORD"] = "hunter2secret"

    checker.check_database_target(env)

    assert not any("hunter2secret" in line for line in checker.ERRORS)


def test_an_absent_url_is_fine(checker):
    """The parts alone are a valid, unambiguous configuration."""
    env = {k: v for k, v in AGREEING.items() if k != "DATABASE_URL"}

    checker.check_database_target(env)

    assert checker.ERRORS == []
    assert any("single source" in line for line in checker.OK)


def test_a_routable_allowed_hosts_passes(checker):
    checker.check_allowed_hosts({"ALLOWED_HOSTS": "clinic.example.com"})

    assert checker.ERRORS == []


def test_a_missing_allowed_hosts_is_an_error(checker):
    checker.check_allowed_hosts({})

    assert checker.ERRORS


def test_a_leaked_test_hostname_is_an_error(checker):
    """Means the development default was shipped rather than edited."""
    checker.check_allowed_hosts(
        {"ALLOWED_HOSTS": "clinic.example.com,testserver"}
    )

    assert checker.ERRORS


def test_loopback_alone_is_an_error(checker):
    """Every request nginx forwards would be rejected."""
    checker.check_allowed_hosts({"ALLOWED_HOSTS": "localhost,127.0.0.1"})

    assert checker.ERRORS


def test_a_percent_encoded_password_is_not_reported(checker):
    """The parts hold the raw value; a URL has to encode it."""
    env = dict(AGREEING)
    env["POSTGRES_PASSWORD"] = "p@ss/word"
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://app:p%40ss%2Fword@db:5432/helpdoctor"
    )

    checker.check_database_target(env)

    assert checker.ERRORS == []
