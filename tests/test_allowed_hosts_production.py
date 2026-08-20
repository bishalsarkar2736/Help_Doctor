"""Production must name the hostnames it serves, or refuse to start.

WHY THIS MATTERS MORE THAN IT LOOKS
The Host header is client-supplied and nginx forwards it verbatim, so anything
downstream that trusts it inherits that: absolute URLs in password-reset mail,
cache keys, tenant resolution. ALLOWED_HOSTS is the allowlist that stops a forged
one at the door.

The failure mode is asymmetric, which is why the validator exists. Ship the
development default to production and the allowlist accepts only loopback, so
every request nginx forwards is rejected with 400 -- a total outage from a
configuration file that looked fine. Refusing to start says so at startup
instead.

WHAT WAS MISSING
Three things, and none of them was the validator: .env.example had no
ALLOWED_HOSTS line at all, neither CONFIGURATION.md nor DEPLOYMENT.md mentioned
it, and the validator accepted "*". That last one is the interesting case -- it
is not a hole, it is a trap. TrustedHostMiddleware compares by equality, not by
glob, so "*" matches a Host of literally "*" and nothing else: it does not open
the allowlist, it closes it. A line that reads like it disabled the check
produces a complete outage discovered only when traffic arrives.

NOTHING HERE NAMES A REAL HOSTNAME. Every value is an obvious placeholder.
"""

import pathlib

import pytest

from app.config import Settings

REPO = pathlib.Path(__file__).parent.parent

ENV_EXAMPLE = REPO / ".env.example"
CONFIG_DOC = REPO / "docs" / "CONFIGURATION.md"
DEPLOY_DOC = REPO / "docs" / "DEPLOYMENT.md"
COMPOSE = REPO / "docker-compose.yml"

# Placeholders. `.test` is reserved by RFC 6761 and resolves nowhere.
PROD_HOSTS = "app.placeholder.test,www.app.placeholder.test"


def _environment(**overrides) -> dict:
    """A complete, obviously-fake environment for constructing Settings.

    Required fields are derived from the model rather than hard-coded, so adding
    a required setting does not silently turn these tests into a check of
    something else.
    """
    special = {
        "POSTGRES_PASSWORD": "placeholder",
        "JWT_SECRET_KEY": "x" * 40,
        "MAIL_FROM": "noreply@placeholder-mail-xyz.com",
    }

    env = {}

    for name, field in Settings.model_fields.items():
        if not field.is_required():
            continue

        if name in special:
            env[name] = special[name]
        elif "URL" in name:
            env[name] = "https://gateway.placeholder-xyz.com"
        else:
            env[name] = "placeholder"

    env.update(overrides)

    return env


def _build(**overrides) -> Settings:
    """Settings from an explicit environment, never from a .env on disk."""
    return Settings(_env_file=None, **_environment(**overrides))


# ---------------------------------------------------------------------------
# Production fails closed
# ---------------------------------------------------------------------------


def test_production_refuses_the_development_default():
    """The concrete case: .env.docker leaves ALLOWED_HOSTS unset, so the app
    falls back to a default containing `testserver`."""
    with pytest.raises(ValueError, match="test-only hostnames"):
        _build(ENV="production")


def test_production_refuses_an_empty_value():
    with pytest.raises(ValueError, match="must name the hostnames"):
        _build(ENV="production", ALLOWED_HOSTS="")


def test_production_refuses_a_whitespace_only_value():
    with pytest.raises(ValueError, match="must name the hostnames"):
        _build(ENV="production", ALLOWED_HOSTS="  ,  ,")


def test_production_refuses_loopback_only():
    """Loopback alone rejects everything nginx forwards, so it is indistinguishable
    from having configured nothing."""
    with pytest.raises(ValueError, match="must name the hostnames"):
        _build(ENV="production", ALLOWED_HOSTS="localhost,127.0.0.1")


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "app.placeholder.test,*",
        "**",
        "**.placeholder.test",
        "foo.*.placeholder.test",
        "*.*.placeholder.test",
        "*.placeholder",          # single-label base would delegate a whole TLD
    ],
)
def test_production_refuses_wildcards(value):
    """Not a hole -- a trap. These are not matched as patterns anywhere, so a
    wildcard in any of these positions matches nothing and rejects every real
    request: an outage produced by a line that reads like it disabled the check.

    `*.<base>` is no longer in this list. It IS matched, by an explicit rule in
    TrustedHostMiddleware that admits exactly one additional label and validates
    it as a tenant subdomain -- see tests/test_trusted_host_wildcard.py. A bare
    `*` remains refused for the original reason.
    """
    with pytest.raises(ValueError, match="literal hostnames, not patterns"):
        _build(ENV="production", ALLOWED_HOSTS=value)


def test_production_accepts_a_single_leading_wildcard():
    """The one supported form, added for tenant subdomains."""
    settings = _build(
        ENV="production",
        ALLOWED_HOSTS="placeholder.test,*.placeholder.test",
    )

    assert settings.allowed_host_suffixes == ["placeholder.test"]
    assert "*.placeholder.test" not in settings.allowed_hosts_list


def test_the_wildcard_message_explains_the_consequence():
    """A refusal that does not say why invites someone to work around it."""
    with pytest.raises(ValueError) as caught:
        _build(ENV="production", ALLOWED_HOSTS="*")

    message = str(caught.value)

    assert "equality" in message
    assert "rejects every real request" in message


# ---------------------------------------------------------------------------
# Production succeeds when told the truth
# ---------------------------------------------------------------------------


def test_production_accepts_explicit_hostnames():
    settings = _build(ENV="production", ALLOWED_HOSTS=PROD_HOSTS)

    hosts = settings.allowed_hosts_list

    assert "app.placeholder.test" in hosts
    assert "www.app.placeholder.test" in hosts


def test_loopback_is_still_accepted_in_production():
    """The container healthcheck calls http://localhost:8000/health/live even in
    production, so these are always accepted and need not be configured."""
    hosts = _build(ENV="production", ALLOWED_HOSTS=PROD_HOSTS).allowed_hosts_list

    assert "localhost" in hosts
    assert "127.0.0.1" in hosts


def test_production_hosts_never_include_a_wildcard():
    hosts = _build(ENV="production", ALLOWED_HOSTS=PROD_HOSTS).allowed_hosts_list

    assert not any("*" in host for host in hosts)


# ---------------------------------------------------------------------------
# Development and staging are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["development", "staging"])
def test_non_production_starts_on_the_default(env):
    """The validator is production-only on purpose: local work and staging are
    reached over loopback, and requiring real hostnames there would break both."""
    settings = _build(ENV=env)

    assert "localhost" in settings.allowed_hosts_list
    assert "testserver" in settings.allowed_hosts_list


@pytest.mark.parametrize("env", ["development", "staging"])
def test_non_production_is_not_subject_to_the_production_rules(env):
    """Including the wildcard rule. Tightening it everywhere would have broken
    staging, which is generated from .env.example."""
    for value in ("", "*", "localhost"):
        settings = _build(ENV=env, ALLOWED_HOSTS=value)

        assert settings.allowed_hosts_list  # loopback always present


# ---------------------------------------------------------------------------
# The middleware still enforces what settings declare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_configured_host_is_accepted(client):
    """`localhost` is in the test environment's allowlist."""
    response = await client.get("/health/live", headers={"Host": "localhost"})

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host", ["evil.placeholder.test", "app.placeholder.test", "*"]
)
async def test_an_unconfigured_host_is_rejected(client, host):
    """Including a host that WOULD be valid in production but is not configured
    here, and the literal `*`."""
    response = await client.get("/health/live", headers={"Host": host})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "InvalidHost"


@pytest.mark.asyncio
async def test_the_metrics_exemption_is_unchanged(client):
    """The previous milestone's carve-out must survive this one."""
    assert (
        await client.get("/metrics", headers={"Host": "api:8000"})
    ).status_code == 200
    assert (
        await client.get("/health/live", headers={"Host": "api:8000"})
    ).status_code == 400


# ---------------------------------------------------------------------------
# The variable is discoverable
# ---------------------------------------------------------------------------


def test_env_example_documents_the_variable():
    """A deployer copying .env.example previously got no ALLOWED_HOSTS line at
    all, then a startup refusal with nothing to point them at."""
    text = ENV_EXAMPLE.read_text()

    assert "ALLOWED_HOSTS=" in text
    assert "production" in text.lower()


def test_env_example_default_is_safe_for_local_work():
    """It must not become a real hostname, and it must not be a wildcard."""
    line = next(
        raw for raw in ENV_EXAMPLE.read_text().splitlines()
        if raw.startswith("ALLOWED_HOSTS=")
    )

    value = line.split("=", 1)[1]

    assert "*" not in value
    assert "localhost" in value


@pytest.mark.parametrize("doc", [CONFIG_DOC, DEPLOY_DOC], ids=lambda p: p.name)
def test_the_docs_mention_the_variable(doc):
    assert "ALLOWED_HOSTS" in doc.read_text()


def test_the_production_checklist_includes_it():
    text = CONFIG_DOC.read_text()

    checklist = text[text.index("Production `.env` checklist"):]

    assert "ALLOWED_HOSTS" in checklist


# ---------------------------------------------------------------------------
# Compose must not blank the value
# ---------------------------------------------------------------------------


def test_compose_does_not_pass_allowed_hosts_through_the_shell():
    """A deliberate absence, verified because it looks like an omission.

    Adding `environment: - ALLOWED_HOSTS` to a service makes compose inject the
    variable EMPTY when the deploying shell has not exported it, overriding
    whatever env_file supplies. Measured: with the host variable unset the
    container saw `ALLOWED_HOSTS=` even though its env_file set a value.

    In production that is caught by the validator rather than served, so it fails
    closed -- but it breaks a correctly configured deployment for the sake of a
    convenience nobody asked for. env_file is the mechanism.
    """
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor(
        "!",
        lambda loader, suffix, node: (
            loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_mapping(node)
            if isinstance(node, yaml.MappingNode)
            else loader.construct_scalar(node)
        ),
    )

    services = yaml.load(COMPOSE.read_text(), Loader=Loader)["services"]

    for name, service in services.items():
        environment = service.get("environment") or {}

        keys = (
            set(environment)
            if isinstance(environment, dict)
            else {entry.split("=")[0] for entry in environment}
        )

        assert "ALLOWED_HOSTS" not in keys, (
            f"{name} passes ALLOWED_HOSTS through compose, which blanks it "
            "whenever the deploying shell has not exported it"
        )
