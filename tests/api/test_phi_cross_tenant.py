"""Tenant isolation for PHI and for the PHI access log itself.

Two distinct questions, and both matter:

1. Can clinic A's staff READ clinic B's patient data?
2. Can clinic A's admin read the ACCESS LOG of clinic B?

The second is easy to overlook. An access log is metadata about patients — who
was treated where, by whom, and when — so leaking it across tenants is itself a
disclosure, even though it contains no diagnoses.

Every test here pairs a denial with the corresponding allowed case, so a
regression that breaks the feature outright cannot masquerade as good security.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.phi_access_log import PHIAccessLog, PHIResourceType


# ---------------------------------------------------------------------------
# 1. Cross-tenant PHI reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doctor_cannot_read_a_patient_from_another_clinic(
    client, other_clinic_patient, auth_doctor
):
    """Clinic A's doctor has no treatment relationship with clinic B's patient."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_doctor["headers"]
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_the_other_clinics_own_doctor_can_read_them(
    client, other_clinic_patient, other_clinic_doctor
):
    """The paired allow-case: denial above is isolation, not a broken endpoint."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == other_clinic_patient.id


@pytest.mark.asyncio
async def test_admin_cannot_read_another_clinics_patient_history(
    client, other_clinic_patient, auth_admin, second_clinic
):
    """Even naming clinic B explicitly must not grant clinic A's admin access."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}/history",
        params={"clinic_id": second_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_cross_tenant_denial_writes_no_phi_access_row(
    client, db, other_clinic_patient, auth_doctor
):
    """A refused read is not an access and must not be recorded as one.

    Logging denials here would put clinic B's patient ids into rows tagged with
    clinic A — the log would itself become a cross-tenant leak.
    """

    await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_doctor["headers"]
    )

    rows = (
        await db.scalars(
            select(PHIAccessLog).where(
                PHIAccessLog.patient_id == other_clinic_patient.id,
                PHIAccessLog.actor_user_id == auth_doctor["user"].id,
            )
        )
    ).all()
    assert rows == [], "a denied read was recorded as a PHI access"


@pytest.mark.asyncio
async def test_access_is_recorded_against_the_clinic_it_happened_in(
    client, db, other_clinic_patient, other_clinic_doctor, second_clinic
):
    res = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )
    assert res.status_code == 200

    log = await db.scalar(
        select(PHIAccessLog)
        .where(PHIAccessLog.patient_id == other_clinic_patient.id)
        .order_by(PHIAccessLog.id.desc())
    )
    assert log is not None
    assert log.clinic_id == second_clinic.id, (
        "access was attributed to the wrong clinic, which would hide it from "
        "the owning clinic's review and expose it to another's"
    )


# ---------------------------------------------------------------------------
# 2. Cross-tenant reads of the access log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_query_another_clinics_access_log(
    client, other_clinic_patient, other_clinic_doctor, auth_admin, second_clinic
):
    # Generate a real access inside clinic B first.
    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    # Clinic A's admin asks for clinic B's log by id.
    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": second_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_admin_querying_their_own_clinic_sees_only_their_own_rows(
    client,
    db,
    other_clinic_patient,
    other_clinic_doctor,
    auth_admin,
    auth_doctor,
    patient_user,
    default_clinic,
    appointment_factory,
):
    """The filter must be the resolved clinic, not one the caller supplies."""

    # An access in clinic B...
    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    # ...and one in clinic A.
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )
    await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()["items"]
    assert all(r["clinic_id"] == default_clinic.id for r in body)
    assert all(r["patient_id"] != other_clinic_patient.id for r in body), (
        "clinic B's patient appeared in clinic A's access log"
    )


@pytest.mark.asyncio
async def test_filtering_by_another_clinics_patient_returns_nothing(
    client, other_clinic_patient, other_clinic_doctor, auth_admin, default_clinic
):
    """Naming a foreign patient id must not bypass the clinic scope."""

    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    res = await client.get(
        "/admin/phi-access",
        params={
            "clinic_id": default_clinic.id,
            "patient_id": other_clinic_patient.id,
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total_count"] == 0


@pytest.mark.asyncio
async def test_non_admin_roles_cannot_read_the_access_log(
    client, auth_doctor, auth_patient, default_clinic
):
    for headers in (auth_doctor["headers"], auth_patient["headers"]):
        res = await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id},
            headers=headers,
        )
        assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_the_access_log_is_reachable_at_all(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic,
    appointment_factory,
):
    """Paired allow-case for the denials above."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )
    await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()["items"]
    assert body, "no rows returned despite a recorded access"
    assert body[0]["resource_type"] == PHIResourceType.PATIENT_PROFILE
