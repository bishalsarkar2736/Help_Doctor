import pytest

from app.core.time import utc_now
from app.models.prescription import PrescriptionStatus


@pytest.mark.asyncio
async def test_my_prescriptions_excludes_drafts_and_old_revisions(
    client, db, doctor, auth_patient, prescription_factory
):
    pid = auth_patient["user"].id

    issued = await prescription_factory(
        doctor_id=doctor.id,
        patient_id=pid,
        status=PrescriptionStatus.ISSUED,
        issued_at=utc_now(),
    )

    # Doctor's work-in-progress — must NOT be visible to the patient.
    await prescription_factory(
        doctor_id=doctor.id,
        patient_id=pid,
        status=PrescriptionStatus.DRAFT,
    )

    # An old, superseded revision — must NOT be visible.
    await prescription_factory(
        doctor_id=doctor.id,
        patient_id=pid,
        status=PrescriptionStatus.SUPERSEDED,
        is_latest_revision=False,
    )

    res = await client.get("/prescriptions/me", headers=auth_patient["headers"])
    assert res.status_code == 200

    body = res.json()
    ids = {p["id"] for p in body}
    statuses = {p["status"] for p in body}

    assert issued.id in ids
    assert "DRAFT" not in statuses
    assert "SUPERSEDED" not in statuses
    assert all(p["is_latest_revision"] for p in body)


@pytest.mark.asyncio
async def test_my_prescriptions_requires_patient(client, auth_doctor):
    res = await client.get("/prescriptions/me", headers=auth_doctor["headers"])
    assert res.status_code == 403
