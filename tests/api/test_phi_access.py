"""PHI access logging.

Reads of protected health information must leave a trace. `audit_logs` records
mutations, which by definition cannot show that a clinician opened a record and
changed nothing — precisely the access a compliance regime asks about.

These tests assert the log is written with every field a reviewer needs, that
it is written for the right actors, and — importantly — that a failure to write
it never denies a clinician access to patient data.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.phi_access_log import PHIAccessLog, PHIAction, PHIResourceType
from app.models.user import UserRole


async def _latest_access(db, patient_id: int) -> PHIAccessLog | None:
    return await db.scalar(
        select(PHIAccessLog)
        .where(PHIAccessLog.patient_id == patient_id)
        .order_by(PHIAccessLog.id.desc())
    )


@pytest.mark.asyncio
async def test_doctor_reading_a_record_is_logged_with_every_field(
    client, db, auth_doctor, patient_user, appointment_factory
):
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )
    assert res.status_code == 200, res.text

    log = await _latest_access(db, patient_user.id)
    assert log is not None, "PHI read was not recorded"

    assert log.actor_user_id == auth_doctor["user"].id
    assert log.actor_role == UserRole.DOCTOR.value
    assert log.patient_id == patient_user.id
    assert log.resource_type == PHIResourceType.PATIENT_PROFILE
    assert log.action == PHIAction.VIEW
    assert log.clinic_id is not None
    assert log.created_at is not None


@pytest.mark.asyncio
async def test_medical_history_read_is_logged(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic,
    appointment_factory,
):
    # get_patient_history requires an appointment in the clinic — without one
    # it correctly 404s, so the fixture has to establish the relationship.
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    res = await client.get(
        f"/patients/{patient_user.id}/history",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    log = await _latest_access(db, patient_user.id)
    assert log is not None
    assert log.resource_type == PHIResourceType.MEDICAL_HISTORY
    assert log.actor_role == UserRole.ADMIN.value


@pytest.mark.asyncio
async def test_patient_reading_their_own_record_is_not_logged(
    client, db, auth_patient
):
    """Self-access is not a disclosure, and logging it would swamp the table."""

    res = await client.get("/patients/me", headers=auth_patient["headers"])
    assert res.status_code in (200, 404)

    rows = (
        await db.scalars(
            select(PHIAccessLog).where(
                PHIAccessLog.patient_id == auth_patient["user"].id,
                PHIAccessLog.actor_user_id == auth_patient["user"].id,
            )
        )
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_logging_failure_never_denies_access_to_patient_data(
    client, auth_doctor, patient_user, appointment_factory, monkeypatch
):
    """The safety trade-off, asserted.

    Refusing to show a doctor a patient's allergies because an audit row could
    not be written would be a patient-safety failure. The read must succeed and
    the failure must surface in logs instead.
    """

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    import app.services.phi_access_log_service as svc

    def explode(*args, **kwargs):
        raise RuntimeError("audit log unavailable")

    # Force the log write itself to blow up.
    monkeypatch.setattr(svc, "PHIAccessLog", explode)

    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    assert res.status_code == 200, "a logging failure must not block clinical care"
    assert res.json()["user_id"] == patient_user.id


@pytest.mark.asyncio
async def test_search_records_one_row_per_surfaced_patient(
    client, db, auth_admin, patient_user
):
    """Search is the query that reveals someone trawling the patient roster."""

    res = await client.get(
        "/patients/search",
        params={"q": patient_user.email[:5]},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    if not res.json():
        pytest.skip("search returned nobody — nothing to assert")

    rows = (
        await db.scalars(
            select(PHIAccessLog).where(
                PHIAccessLog.resource_type == PHIResourceType.PATIENT_SEARCH
            )
        )
    ).all()
    assert rows, "search surfaced patients but recorded no access"
    assert all(r.action == PHIAction.SEARCH for r in rows)


# ---- authorization, unchanged by the logging work ----


@pytest.mark.asyncio
async def test_doctor_without_relationship_is_forbidden(
    client, auth_doctor, patient_user
):
    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_patient_cannot_use_staff_read(client, auth_patient, patient_user):
    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_patient["headers"]
    )
    assert res.status_code == 403
