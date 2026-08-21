"""The two tenant-routing settings, checked before a deploy rather than after.

CLINIC_BASE_DOMAIN and ALLOWED_HOSTS are read by different code — the tenant
resolver and TrustedHostMiddleware — and nothing at runtime notices when they
disagree. A wildcard without a base domain 404s every tenant request; a base
domain without a wildcard 400s every tenant request. Neither says why, so the
gate has to say it here.
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
        "check_prod_env_tenant_hosts_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    module.ERRORS.clear()
    module.WARNINGS.clear()
    module.OK.clear()

    return module


def _errors(checker, **env) -> list[str]:
    checker.check_clinic_base_domain(env)
    checker.check_trusted_proxy_ips(env)
    return list(checker.ERRORS)


# ---------------------------------------------------------------------------
# CLINIC_BASE_DOMAIN — presence and shape
# ---------------------------------------------------------------------------


def test_a_valid_base_domain_passes(checker):
    checker.check_clinic_base_domain(
        {"CLINIC_BASE_DOMAIN": "example.com", "ALLOWED_HOSTS": "example.com"}
    )

    assert not checker.ERRORS


def test_the_placeholder_is_refused(checker):
    """A single label, so it fails the same rule a bare TLD would."""
    checker.check_clinic_base_domain(
        {"CLINIC_BASE_DOMAIN": "__REPLACE_WITH_YOUR_DOMAIN__"}
    )

    assert checker.ERRORS


@pytest.mark.parametrize(
    "value",
    [
        "*.example.com",           # names a pattern, not the base
        "https://example.com",     # scheme
        "example.com/tenants",     # path
        "example.com:443",         # port
        "localhost",               # single label — a tenant under a TLD
        "com",
        "example..com",            # empty label
        "-bad.example.com",        # not a DNS label
        "under_score.com",
    ],
)
def test_malformed_base_domains_are_refused(checker, value):
    checker.check_clinic_base_domain({"CLINIC_BASE_DOMAIN": value})

    assert checker.ERRORS, f"{value!r} should have been refused"


def test_the_label_rule_is_the_shared_one(checker):
    """Reused from app/domain/clinics/subdomain.py rather than restated, so the
    gate cannot drift from what the allowlist and the resolver enforce."""
    assert hasattr(checker, "validate_subdomain")
    assert hasattr(checker, "InvalidSubdomain")


# ---------------------------------------------------------------------------
# CLINIC_BASE_DOMAIN — agreement with ALLOWED_HOSTS
# ---------------------------------------------------------------------------


def test_a_matching_wildcard_passes(checker):
    checker.check_clinic_base_domain(
        {
            "CLINIC_BASE_DOMAIN": "example.com",
            "ALLOWED_HOSTS": "example.com,*.example.com",
        }
    )

    assert not checker.ERRORS


def test_a_mismatched_wildcard_is_refused(checker):
    """The failure nothing at runtime would report."""
    checker.check_clinic_base_domain(
        {
            "CLINIC_BASE_DOMAIN": "example.com",
            "ALLOWED_HOSTS": "other.com,*.other.com",
        }
    )

    assert checker.ERRORS
    assert "disagree" in checker.ERRORS[0]


def test_a_wildcard_without_a_base_domain_is_refused(checker):
    """Those hosts pass the allowlist and then resolve to no clinic."""
    checker.check_clinic_base_domain(
        {"CLINIC_BASE_DOMAIN": "", "ALLOWED_HOSTS": "example.com,*.example.com"}
    )

    assert checker.ERRORS
    assert "404" in checker.ERRORS[0]


def test_no_wildcard_and_no_base_domain_is_single_tenant(checker):
    """A one-hostname deployment is a legitimate configuration, not an error."""
    checker.check_clinic_base_domain(
        {"CLINIC_BASE_DOMAIN": "", "ALLOWED_HOSTS": "example.com"}
    )

    assert not checker.ERRORS
    assert any("single-tenant" in m for m in checker.OK)


def test_a_base_domain_without_a_wildcard_is_allowed(checker):
    """Not required to be an error: tenant hosts would be 400'd, but the
    operator may be enumerating them literally in ALLOWED_HOSTS."""
    checker.check_clinic_base_domain(
        {
            "CLINIC_BASE_DOMAIN": "example.com",
            "ALLOWED_HOSTS": "example.com,clinic-a.example.com",
        }
    )

    assert not checker.ERRORS


# ---------------------------------------------------------------------------
# TRUSTED_PROXY_IPS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["172.18.0.0/16", "10.0.0.5", "172.18.0.0/16,10.0.0.5", "fd00::/8"],
)
def test_valid_proxy_networks_pass(checker, value):
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": value})

    assert not checker.ERRORS


def test_empty_is_refused(checker):
    """Behind a proxy this makes per-IP limits apply to everyone at once."""
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": ""})

    assert checker.ERRORS


def test_a_missing_key_is_refused(checker):
    checker.check_trusted_proxy_ips({})

    assert checker.ERRORS


def test_a_star_is_refused(checker):
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": "*"})

    assert checker.ERRORS
    assert "evadable" in checker.ERRORS[0]


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0"])
def test_a_default_route_is_refused_like_a_star(checker, value):
    """'*' spelled as a network. Refusing one and not the other would be a hole
    with a different syntax."""
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": value})

    assert checker.ERRORS


@pytest.mark.parametrize(
    "value",
    ["not-an-ip", "172.18.0.0/33", "999.1.1.1", "__REPLACE_WITH_PROXY_NETWORK_CIDR__"],
)
def test_malformed_entries_are_refused(checker, value):
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": value})

    assert checker.ERRORS


def test_one_bad_entry_refuses_the_whole_list(checker):
    """A list that is half valid is not half trusted."""
    checker.check_trusted_proxy_ips({"TRUSTED_PROXY_IPS": "172.18.0.0/16,nonsense"})

    assert checker.ERRORS


# ---------------------------------------------------------------------------
# Both are actually wired into check()
# ---------------------------------------------------------------------------


def test_the_new_checks_run_as_part_of_check(checker):
    """A check nothing calls is a check that never runs."""
    import inspect

    source = inspect.getsource(checker.check)

    assert "check_clinic_base_domain" in source
    assert "check_trusted_proxy_ips" in source
