"""PUT /admin/clinic/{id}/subdomain — the platform's tenant-hostname control.

Authorization is the first section on purpose. A subdomain is unique across
every tenant and has to exist in DNS and on a certificate the clinic does not
control, so choosing one is platform-plane state — the same plane as creating,
suspending or archiving a clinic, and deliberately not something a clinic admin
can do for themselves.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.clinic import Clinic
from app.schemas.clinic_schema import ClinicSubdomainUpdate
from app.services import clinic_service
from app.services.clinic_service import set_clinic_subdomain
from app.try_except.exceptions import BadRequestError, NotFoundError


def _url(clinic_id: int) -> str:
    return f"/admin/clinic/{clinic_id}/subdomain"


def _unique() -> str:
    return f"clinic-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_may_set_the_subdomain(
    client, default_clinic, auth_super_admin
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "citycare"},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json()["subdomain"] == "citycare"


@pytest.mark.asyncio
async def test_a_clinic_admin_may_not_set_the_subdomain(
    client, default_clinic, auth_admin
):
    """Not merely 'someone else's clinic' — an admin may not set even their own.
    A tenant choosing its own label could claim any free name on the platform's
    domain, including one the platform intends to use."""
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "citycare"},
        headers=auth_admin["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_doctor_may_not_set_the_subdomain(
    client, default_clinic, auth_doctor
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "citycare"},
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_patient_may_not_set_the_subdomain(
    client, default_clinic, auth_patient
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "citycare"},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_may_not_set_the_subdomain(
    client, default_clinic
):
    response = await client.put(
        _url(default_clinic.id), json={"subdomain": "citycare"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Assignment and validation, over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_value_is_normalised_before_it_is_stored(
    client, db, default_clinic, auth_super_admin
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "  CityCare  "},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 200
    assert response.json()["subdomain"] == "citycare"

    stored = await db.scalar(
        select(Clinic).where(Clinic.id == default_clinic.id)
    )
    assert stored.subdomain == "citycare"


@pytest.mark.asyncio
async def test_a_reserved_subdomain_is_rejected(
    client, default_clinic, auth_super_admin
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "api"},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_malformed_subdomain_is_rejected(
    client, default_clinic, auth_super_admin
):
    response = await client.put(
        _url(default_clinic.id),
        json={"subdomain": "-nope-"},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_omitting_the_field_is_refused_rather_than_clearing_it(
    client, default_clinic, auth_super_admin
):
    """The whole reason this endpoint is separate from ClinicUpdate: an omitted
    field must never be read as 'remove the hostname'."""
    response = await client.put(
        _url(default_clinic.id),
        json={},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_clinic_is_a_404(client, auth_super_admin):
    response = await client.put(
        _url(999_999),
        json={"subdomain": "citycare"},
        headers=auth_super_admin["headers"],
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_null_clears_the_subdomain(
    client, db, default_clinic, auth_super_admin
):
    h = auth_super_admin["headers"]

    await client.put(_url(default_clinic.id), json={"subdomain": "citycare"}, headers=h)

    response = await client.put(
        _url(default_clinic.id), json={"subdomain": None}, headers=h
    )

    assert response.status_code == 200
    assert response.json()["subdomain"] is None

    stored = await db.scalar(
        select(Clinic).where(Clinic.id == default_clinic.id)
    )
    assert stored.subdomain is None


# ---------------------------------------------------------------------------
# Uniqueness, at the service layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_duplicate_subdomain_is_refused(db, default_clinic):
    other = Clinic(name=f"Other {uuid.uuid4()}", subdomain="taken")
    db.add(other)
    await db.flush()

    with pytest.raises(BadRequestError) as exc:
        await set_clinic_subdomain(
            db=db,
            clinic_id=default_clinic.id,
            payload=ClinicSubdomainUpdate(subdomain="taken"),
        )

    assert "subdomain" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_a_duplicate_differing_only_in_case_is_refused(db, default_clinic):
    other = Clinic(name=f"Other {uuid.uuid4()}", subdomain="taken")
    db.add(other)
    await db.flush()

    with pytest.raises(BadRequestError):
        await set_clinic_subdomain(
            db=db,
            clinic_id=default_clinic.id,
            payload=ClinicSubdomainUpdate(subdomain="TAKEN"),
        )


@pytest.mark.asyncio
async def test_re_sending_a_clinics_own_subdomain_is_not_a_duplicate(
    db, default_clinic
):
    """A clinic must not collide with itself, or the assignment would be a
    one-shot that could never be re-applied."""
    value = _unique()

    await set_clinic_subdomain(
        db=db,
        clinic_id=default_clinic.id,
        payload=ClinicSubdomainUpdate(subdomain=value),
    )

    again = await set_clinic_subdomain(
        db=db,
        clinic_id=default_clinic.id,
        payload=ClinicSubdomainUpdate(subdomain=value),
    )

    assert again.subdomain == value


@pytest.mark.asyncio
async def test_an_unknown_clinic_raises_not_found(db):
    with pytest.raises(NotFoundError):
        await set_clinic_subdomain(
            db=db,
            clinic_id=999_999,
            payload=ClinicSubdomainUpdate(subdomain="citycare"),
        )


# ---------------------------------------------------------------------------
# The race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_refuses_a_duplicate_the_pre_check_missed(
    db, default_clinic, monkeypatch
):
    """uq_clinic_subdomain_lower is the authority; the pre-check is a courtesy.

    Both refusals carry the same message, so this records which path ran — the
    assertion would otherwise pass even if the constraint were never reached.
    """
    other = Clinic(name=f"Other {uuid.uuid4()}", subdomain="contested")
    db.add(other)
    await db.flush()

    async def _always_free(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(clinic_service, "_subdomain_taken", _always_free)

    from_database = []
    original = clinic_service._duplicate_error

    def _record(error):
        from_database.append(error)
        return original(error)

    monkeypatch.setattr(clinic_service, "_duplicate_error", _record)

    with pytest.raises(BadRequestError) as exc:
        await set_clinic_subdomain(
            db=db,
            clinic_id=default_clinic.id,
            payload=ClinicSubdomainUpdate(subdomain="contested"),
        )

    assert "subdomain" in str(exc.value).lower()
    assert from_database, (
        "the refusal came from the pre-check, not the unique index — this test "
        "did not exercise the race it claims to"
    )
