"""Host -> subdomain -> clinic, and the line it must not cross.

The Host header is client-supplied. It may say WHICH tenant a request is for;
it may never say that the caller is entitled to that tenant. These tests are
mostly about the second half: that a principal belonging to one clinic cannot
be moved to another by editing a hostname.
"""

import uuid

import pytest

from app.config import get_settings
from app.domain.clinics.subdomain import subdomain_from_host
from app.models.clinic import Clinic, ClinicStatus
from app.models.user import User, UserRole
from app.security.jwt import hash_password
from app.services.clinic_context import clinic_for_host, resolve_clinic_context
from app.try_except.exceptions import ForbiddenError, NotFoundError

BASE = "helpdoctor.com"


@pytest.fixture(autouse=True)
def _base_domain(monkeypatch):
    """Host resolution is inert until an apex is configured."""
    settings = get_settings()
    monkeypatch.setattr(settings, "CLINIC_BASE_DOMAIN", BASE, raising=False)
    yield


async def _clinic(db, subdomain, status=ClinicStatus.ACTIVE) -> Clinic:
    clinic = Clinic(
        name=f"Clinic {uuid.uuid4()}",
        subdomain=subdomain,
        status=status,
    )
    db.add(clinic)
    await db.flush()
    return clinic


async def _admin_of(db, clinic) -> User:
    user = User(
        email=f"admin-{uuid.uuid4()}@test.com",
        full_name="Clinic Admin",
        hashed_password=hash_password("secret123"),
        role=UserRole.ADMIN,
        is_active=True,
        is_email_verified=True,
        clinic_id=clinic.id,
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Parsing: which hosts name a tenant at all
# ---------------------------------------------------------------------------


def test_a_single_label_under_the_apex_is_a_tenant():
    assert subdomain_from_host(f"clinic-a.{BASE}", BASE) == "clinic-a"


def test_the_port_is_ignored():
    assert subdomain_from_host(f"clinic-a.{BASE}:8000", BASE) == "clinic-a"


def test_the_host_is_lowercased():
    assert subdomain_from_host(f"Clinic-A.{BASE}", BASE) == "clinic-a"


@pytest.mark.parametrize(
    "host",
    [
        "helpdoctor.com",              # the apex is the platform, not a tenant
        "a.b.helpdoctor.com",          # nested: one tenant must not prefix many hosts
        "clinic-a.evil.com",           # foreign domain
        "helpdoctor.com.evil.com",     # apex as a prefix of someone else's domain
        "evil-helpdoctor.com",         # apex as a suffix without the dot
        "127.0.0.1",                   # IPv4 literal
        "[::1]:8000",                  # IPv6 literal
        "",                            # empty
        "   ",                         # whitespace
        ":8000",                       # port only
        "-bad.helpdoctor.com",         # malformed label
        "api.helpdoctor.com",          # reserved
        "www.helpdoctor.com",          # reserved
        "grafana.helpdoctor.com",      # reserved: real infrastructure hostname
    ],
)
def test_hosts_that_name_no_tenant(host):
    assert subdomain_from_host(host, BASE) is None


def test_nothing_resolves_when_no_base_domain_is_configured():
    """The default state of every deployment: the feature is off."""
    assert subdomain_from_host(f"clinic-a.{BASE}", None) is None
    assert subdomain_from_host(f"clinic-a.{BASE}", "") is None


# ---------------------------------------------------------------------------
# Lookup: which clinics a Host can reach
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_resolves_to_its_own_clinic(db):
    a = await _clinic(db, "clinic-a")
    b = await _clinic(db, "clinic-b")

    assert (await clinic_for_host(db, f"clinic-a.{BASE}")).id == a.id
    assert (await clinic_for_host(db, f"clinic-b.{BASE}")).id == b.id


@pytest.mark.asyncio
async def test_an_unknown_subdomain_resolves_to_nothing(db):
    assert await clinic_for_host(db, f"no-such-clinic.{BASE}") is None


@pytest.mark.asyncio
async def test_a_suspended_clinic_is_not_reachable_by_host(db):
    """Its users are already blocked from logging in; its hostname must not be
    a way back in."""
    await _clinic(db, "suspended-one", status=ClinicStatus.SUSPENDED)

    assert await clinic_for_host(db, f"suspended-one.{BASE}") is None


@pytest.mark.asyncio
async def test_a_soft_deleted_clinic_is_not_reachable_by_host(db):
    clinic = await _clinic(db, "archived-one")
    clinic.status = ClinicStatus.DELETED
    await db.flush()

    assert await clinic_for_host(db, f"archived-one.{BASE}") is None


@pytest.mark.asyncio
async def test_the_apex_reaches_no_clinic(db):
    await _clinic(db, "clinic-a")

    assert await clinic_for_host(db, BASE) is None


# ---------------------------------------------------------------------------
# Context: Host as a candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unauthenticated_request_gets_the_hosts_clinic(db):
    """Identification, not authorization: the caller is still anonymous."""
    a = await _clinic(db, "clinic-a")

    resolved = await resolve_clinic_context(db, host=f"clinic-a.{BASE}")

    assert resolved.id == a.id


@pytest.mark.asyncio
async def test_an_unknown_host_still_produces_the_existing_not_found(db):
    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, host=f"no-such-clinic.{BASE}")


@pytest.mark.asyncio
async def test_explicit_clinic_id_still_wins(db):
    """Existing precedence is unchanged."""
    a = await _clinic(db, "clinic-a")
    b = await _clinic(db, "clinic-b")

    resolved = await resolve_clinic_context(
        db, clinic_id=b.id, host=f"clinic-a.{BASE}"
    )

    assert resolved.id == b.id


# ---------------------------------------------------------------------------
# The rule: Host must agree with the principal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_principal_on_the_matching_host_is_allowed(db):
    a = await _clinic(db, "clinic-a")
    admin = await _admin_of(db, a)

    resolved = await resolve_clinic_context(
        db, user=admin, host=f"clinic-a.{BASE}"
    )

    assert resolved.id == a.id


@pytest.mark.asyncio
async def test_a_principal_on_another_clinics_host_is_refused(db):
    """The whole point. Clinic B's admin visiting clinic-a.helpdoctor.com is
    refused rather than silently re-scoped to clinic A."""
    a = await _clinic(db, "clinic-a")
    b = await _clinic(db, "clinic-b")
    admin_of_b = await _admin_of(db, b)

    with pytest.raises(ForbiddenError):
        await resolve_clinic_context(db, user=admin_of_b, host=f"clinic-a.{BASE}")

    assert a.id != b.id


@pytest.mark.asyncio
async def test_the_mismatch_is_refused_even_with_an_explicit_clinic_id(db):
    """Naming your own clinic in the query string does not excuse the host."""
    a = await _clinic(db, "clinic-a")
    b = await _clinic(db, "clinic-b")
    admin_of_b = await _admin_of(db, b)

    with pytest.raises(ForbiddenError):
        await resolve_clinic_context(
            db, clinic_id=b.id, user=admin_of_b, host=f"clinic-a.{BASE}"
        )


@pytest.mark.asyncio
async def test_a_principal_with_no_clinic_contradicts_nothing(db):
    """Patients are global identities; they have no tenant to disagree with."""
    a = await _clinic(db, "clinic-a")

    patient = User(
        email=f"patient-{uuid.uuid4()}@test.com",
        full_name="Patient",
        hashed_password=hash_password("secret123"),
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )
    db.add(patient)
    await db.flush()

    resolved = await resolve_clinic_context(
        db, user=patient, host=f"clinic-a.{BASE}"
    )

    assert resolved.id == a.id


@pytest.mark.asyncio
async def test_a_host_that_names_no_tenant_cannot_cause_a_mismatch(db):
    """An unrelated Host must not lock a signed-in user out of their own
    clinic — the check only fires when the host really named a tenant."""
    b = await _clinic(db, "clinic-b")
    admin_of_b = await _admin_of(db, b)

    resolved = await resolve_clinic_context(
        db, user=admin_of_b, host=f"api.{BASE}"
    )

    assert resolved.id == b.id


# ---------------------------------------------------------------------------
# Existing behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dev_header_still_works_outside_production(db, monkeypatch):
    a = await _clinic(db, "clinic-a")

    monkeypatch.setattr(get_settings(), "ENV", "development", raising=False)

    resolved = await resolve_clinic_context(db, dev_clinic_id=a.id)

    assert resolved.id == a.id


@pytest.mark.asyncio
async def test_the_dev_header_is_still_ignored_in_production(db, monkeypatch):
    a = await _clinic(db, "clinic-a")

    monkeypatch.setattr(get_settings(), "ENV", "production", raising=False)

    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, dev_clinic_id=a.id)


@pytest.mark.asyncio
async def test_host_resolution_is_inert_without_a_base_domain(db, monkeypatch):
    """Every deployment today. Adding the seam changed nothing for them."""
    await _clinic(db, "clinic-a")

    monkeypatch.setattr(get_settings(), "CLINIC_BASE_DOMAIN", None, raising=False)

    assert await clinic_for_host(db, f"clinic-a.{BASE}") is None

    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, host=f"clinic-a.{BASE}")
