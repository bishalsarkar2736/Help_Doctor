"""Which clinic a request operates inside.

The scheduling assistant is multi-tenant and every query it makes is scoped by
this. What matters is not only that the right clinic is found, but that a
request which resolves to nothing FAILS — a tenant boundary that degrades to
"the first clinic" or to an unscoped query is worse than one that refuses.

Resolution is deliberately not tied to the Host header. Subdomain routing needs
wildcard DNS and a wildcard certificate that do not exist yet, and building the
assistant against them would couple a feature that can ship now to
infrastructure that cannot.
"""

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.clinic import Clinic, ClinicStatus
from app.models.user import User, UserRole
from app.services.clinic_context import (
    clinic_id_for_user,
    load_active_clinic,
    resolve_clinic_context,
)
from app.try_except.exceptions import NotFoundError


@pytest.fixture
async def active_clinic(db):
    clinic = Clinic(name="Context Clinic", status=ClinicStatus.ACTIVE)
    db.add(clinic)
    await db.commit()
    return clinic


@pytest.fixture
async def suspended_clinic(db):
    clinic = Clinic(name="Suspended Clinic", status=ClinicStatus.SUSPENDED)
    db.add(clinic)
    await db.commit()
    return clinic


# ---------------------------------------------------------------------------
# Only a clinic that is open for business resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_active_clinic_resolves(db, active_clinic):
    clinic = await resolve_clinic_context(db, clinic_id=active_clinic.id)

    assert clinic.id == active_clinic.id


@pytest.mark.asyncio
async def test_an_unknown_clinic_is_not_found(db):
    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, clinic_id=999_999)


@pytest.mark.asyncio
async def test_a_suspended_clinic_does_not_resolve(db, suspended_clinic):
    """Its users' access is revoked; answering for it would send patients to a
    practice that is not operating."""
    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, clinic_id=suspended_clinic.id)


@pytest.mark.asyncio
async def test_a_deleted_clinic_does_not_resolve(db):
    clinic = Clinic(name="Deleted Clinic", status=ClinicStatus.DELETED)
    db.add(clinic)
    await db.commit()

    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, clinic_id=clinic.id)


@pytest.mark.asyncio
async def test_a_soft_deleted_row_does_not_resolve_even_if_active(db):
    """status and deleted_at are written by different flows.

    A row carrying a deletion timestamp is deleted whatever its status says,
    so both are checked rather than trusting one.
    """
    from datetime import datetime, timezone

    clinic = Clinic(
        name="Inconsistent Clinic",
        status=ClinicStatus.ACTIVE,
        deleted_at=datetime.now(timezone.utc),
    )
    db.add(clinic)
    await db.commit()

    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, clinic_id=clinic.id)


@pytest.mark.asyncio
async def test_load_active_clinic_returns_none_rather_than_raising(
    db, suspended_clinic
):
    """The lookup reports absence; the caller decides what that means."""
    assert await load_active_clinic(db, suspended_clinic.id) is None


# ---------------------------------------------------------------------------
# No fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_resolves_when_nothing_is_offered(db, active_clinic):
    """Not "the only clinic", not "the first" — nothing."""
    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db)


@pytest.mark.asyncio
async def test_a_named_clinic_that_fails_does_not_fall_through(
    db, active_clinic, suspended_clinic, doctor_user
):
    """Answering for a different tenant than the caller named is worse than
    refusing, so resolution stops at the first candidate that was offered."""
    with pytest.raises(NotFoundError):
        await resolve_clinic_context(
            db,
            clinic_id=suspended_clinic.id,
            dev_clinic_id=active_clinic.id,
        )


# ---------------------------------------------------------------------------
# The authenticated user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_resolves_to_their_own_clinic(db, active_clinic):
    admin = User(
        email="ctx-admin@test.com",
        hashed_password="x",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id=active_clinic.id,
    )
    db.add(admin)
    await db.commit()

    clinic = await resolve_clinic_context(db, user=admin)

    assert clinic.id == active_clinic.id


@pytest.mark.asyncio
async def test_a_doctor_resolves_through_their_profile(db, auth_doctor):
    clinic_id = auth_doctor["doctor"].clinic_id

    resolved = await clinic_id_for_user(db, auth_doctor["user"])

    assert resolved == clinic_id


@pytest.mark.asyncio
async def test_a_patient_resolves_to_nothing(db, patient_user):
    """Patients are not bound to a clinic anywhere in the schema.

    Guessing one from their appointment history would pick a tenant on their
    behalf, so they have to name it.
    """
    assert await clinic_id_for_user(db, patient_user) is None


@pytest.mark.asyncio
async def test_an_explicit_clinic_wins_over_the_user(db, active_clinic):
    """A clinic-bound admin browsing a public assistant page still gets the
    clinic the request names."""
    other = Clinic(name="Other Clinic", status=ClinicStatus.ACTIVE)
    db.add(other)
    await db.flush()

    admin = User(
        email="ctx-admin2@test.com",
        hashed_password="x",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id=active_clinic.id,
    )
    db.add(admin)
    await db.commit()

    clinic = await resolve_clinic_context(db, clinic_id=other.id, user=admin)

    assert clinic.id == other.id


# ---------------------------------------------------------------------------
# The development header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_development_header_resolves_outside_production(
    db, active_clinic
):
    assert get_settings().ENV != "production"

    clinic = await resolve_clinic_context(db, dev_clinic_id=active_clinic.id)

    assert clinic.id == active_clinic.id


@pytest.mark.asyncio
async def test_production_ignores_the_development_header(
    db, active_clinic, monkeypatch
):
    """Left active it would let any caller name any tenant."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(NotFoundError):
        await resolve_clinic_context(db, dev_clinic_id=active_clinic.id)


@pytest.mark.asyncio
async def test_production_still_resolves_an_explicit_clinic(
    db, active_clinic, monkeypatch
):
    """Only the development shortcut is disabled, not resolution itself."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ENV", "production")

    clinic = await resolve_clinic_context(db, clinic_id=active_clinic.id)

    assert clinic.id == active_clinic.id


# ---------------------------------------------------------------------------
# Nothing already deployed changed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_route_requires_a_clinic_yet(db):
    """Milestone 0 adds the seam and wires nothing to it.

    Asserted so that adding require_clinic to an existing endpoint is a
    deliberate act rather than something that happens by accident.
    """
    import app.main

    source = open(app.main.__file__).read()

    assert "require_clinic" not in source
