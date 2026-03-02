import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError

from app.models.appointment import Appointment, AppointmentStatus


@pytest.mark.asyncio
async def test_doctor_cannot_have_overlapping_appointments(
    db,
    doctor,
    patient_user,
):
    start = datetime.now(timezone.utc)

    appt1 = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=start,
        status=AppointmentStatus.PENDING,
    )
    db.add(appt1)
    await db.flush()
    await db.commit()

    appt2 = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=start + timedelta(minutes=15),
        status=AppointmentStatus.PENDING,
    )
    db.add(appt2)

    with pytest.raises(IntegrityError):
        await db.flush()

    #await db.rollback()
