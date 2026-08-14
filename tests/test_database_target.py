"""Which database the application actually talks to.

Alembic reads DATABASE_URL; the application composed its own connection string
from the POSTGRES_* parts and never looked at it. Setting DATABASE_URL therefore
steered migrations and nothing else — the schema changed in one database while
every query ran against another, silently, until the application started
failing on tables it believed it had created.

Both forms have to keep existing: the postgres container, the healthcheck and
the backup scripts are configured from the parts. So the rule is not that one
of them goes away, but that they can never disagree.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = {
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": 5432,
    "POSTGRES_DB": "helpdoctor",
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "secret$pass",
}


def _settings(**overrides) -> Settings:
    """Settings with the database fields pinned, everything else as configured.

    The other two dozen required fields come from the environment as usual;
    explicit arguments outrank them, so these tests are unaffected by whatever
    database the developer running them happens to point at.
    """
    return Settings(**{**BASE, **overrides})


# ---------------------------------------------------------------------------
# Which value wins
# ---------------------------------------------------------------------------


def test_the_parts_are_used_when_no_url_is_given():
    settings = _settings()

    assert settings.database_url == (
        "postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor"
    )


def test_the_url_wins_when_it_is_given():
    """Alembic already preferred it; the app now agrees rather than differing."""
    url = "postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor"

    assert _settings(DATABASE_URL=url).database_url == url


def test_extra_url_parameters_survive():
    """A managed database hands over sslmode and pooler options in the URL.

    Composing from the parts discarded them, so a connection that had to be
    encrypted quietly was not.
    """
    url = "postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor?ssl=require"

    assert _settings(DATABASE_URL=url).database_url == url


def test_the_composed_url_is_still_available():
    settings = _settings(
        DATABASE_URL="postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor"
    )

    assert "helpdoctor" in settings.composed_database_url


# ---------------------------------------------------------------------------
# Contradictions are refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "postgresql+asyncpg://app:secret%24pass@db:5432/other_db",
            "database",
        ),
        (
            "postgresql+asyncpg://app:secret%24pass@other-host:5432/helpdoctor",
            "host",
        ),
        (
            "postgresql+asyncpg://app:secret%24pass@db:6543/helpdoctor",
            "port",
        ),
    ],
)
def test_a_contradiction_refuses_to_start(url, expected):
    """Host, port and database still have to agree.

    These are the values whose disagreement sends migrations to one database
    and queries to another, which is the failure this validator exists for.
    Privilege separation did not relax any of them.
    """
    with pytest.raises(ValidationError) as exc:
        _settings(DATABASE_URL=url)

    assert expected in str(exc.value)


# ---------------------------------------------------------------------------
# Credentials, which privilege separation deliberately allows to differ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://helpdoctor_app:secret%24pass@db:5432/helpdoctor",
        "postgresql+asyncpg://helpdoctor_app:apppw@db:5432/helpdoctor",
    ],
)
def test_the_runtime_url_may_carry_a_different_role(url):
    """THE POINT OF PRIVILEGE SEPARATION.

    DATABASE_URL names the restricted runtime role while the POSTGRES_* parts
    describe the owner, so a different user and password there is the intended
    configuration rather than a contradiction. Same database, different rights.
    """
    settings = _settings(DATABASE_URL=url)

    assert settings.database_url == url


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "postgresql+asyncpg://other_user:secret%24pass@db:5432/helpdoctor",
            "user",
        ),
        (
            "postgresql+asyncpg://app:rotated%24pass@db:5432/helpdoctor",
            "password",
        ),
    ],
)
def test_the_migration_url_is_still_held_to_the_credentials(url, expected):
    """MIGRATION_DATABASE_URL and the POSTGRES_* parts describe the SAME
    privileged role, so a half-done rotation there is still a contradiction —
    the protection that was relaxed for the runtime URL is kept here."""

    with pytest.raises(ValidationError) as exc:
        _settings(MIGRATION_DATABASE_URL=url)

    assert expected in str(exc.value)


def test_the_migration_url_must_name_the_same_database():
    with pytest.raises(ValidationError) as exc:
        _settings(
            MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://app:secret%24pass@db:5432/other_db"
            )
        )

    assert "database" in str(exc.value)


def test_the_message_names_what_disagrees():
    """A deploy stops here, so the message has to say which value to fix."""
    with pytest.raises(ValidationError) as exc:
        _settings(
            DATABASE_URL="postgresql+asyncpg://app:secret%24pass@db:5432/wrong_db"
        )

    message = str(exc.value)
    assert "wrong_db" in message
    assert "helpdoctor" in message


def test_the_password_value_is_not_echoed():
    """This is raised at startup and lands in logs.

    Asserted on MIGRATION_DATABASE_URL, since that is where a password
    mismatch is still a contradiction.
    """
    with pytest.raises(ValidationError) as exc:
        _settings(
            MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://app:rotated%24pass@db:5432/helpdoctor"
            )
        )

    assert "rotated" not in str(exc.value)


# ---------------------------------------------------------------------------
# Equivalent spellings are not contradictions
# ---------------------------------------------------------------------------


def test_a_percent_encoded_password_is_not_a_conflict():
    """The parts hold the raw password; a URL must encode it."""
    url = "postgresql+asyncpg://app:secret%24pass@db:5432/helpdoctor"

    assert _settings(DATABASE_URL=url).database_url == url


def test_an_omitted_port_is_not_a_conflict():
    """A URL may leave the default port out; that is not a disagreement."""
    url = "postgresql+asyncpg://app:secret%24pass@db/helpdoctor"

    assert _settings(DATABASE_URL=url).database_url == url


def test_an_omitted_password_is_not_a_conflict():
    """Some deployments pass credentials outside the URL entirely."""
    url = "postgresql+asyncpg://app@db:5432/helpdoctor"

    assert _settings(DATABASE_URL=url).database_url == url
