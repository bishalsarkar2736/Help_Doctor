import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.activity_log import ActivityLog


@pytest.mark.asyncio
async def test_doctor_with_appointment_reads_record_and_logs_access(
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
    assert res.json()["user_id"] == patient_user.id

    # The read was recorded as a PHI access event.
    log = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.action == "PHI_ACCESS",
            ActivityLog.entity_id == patient_user.id,
        )
    )
    assert log is not None
    assert log.actor_id == auth_doctor["user"].id
    assert log.entity_type == "patient"


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
