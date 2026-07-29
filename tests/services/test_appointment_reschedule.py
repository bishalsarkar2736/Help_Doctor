from datetime import datetime, timedelta

import pytest

from app.core.time import UTC
from app.core.constants import APPOINTMENT_DURATION_MINUTES
from app.models.appointment import Appointment, AppointmentStatus
from app.services.appointment_service import patient_reschedule_appointment
from app.try_except.exceptions import BadRequestError


def _slot(days_ahead: int) -> datetime:
    dt = (datetime.now(UTC) + timedelta(days=days_ahead)).replace(
        second=0, microsecond=0
    )
    minute = dt.minute - (dt.minute % APPOINTMENT_DURATION_MINUTES)
    return dt.replace(minute=minute, hour=10)


async def _make_appt(db, doctor, patient_user, clinic, status, days_ahead=1):
    appt = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=clinic.id,
        scheduled_at=_slot(days_ahead),
        status=status,
    )
    db.add(appt)
    await db.flush()
    await db.refresh(appt)
    return appt


@pytest.mark.asyncio
async def test_reschedule_confirmed_reopens_to_pending(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    appt = await _make_appt(
        db, doctor, patient_user, default_clinic,
        AppointmentStatus.CONFIRMED, days_ahead=1,
    )

    new_dt = _slot(3)
    await patient_reschedule_appointment(
        db=db,
        user=patient_user,
        appointment_id=appt.id,
        new_datetime=new_dt,
    )

    await db.refresh(appt)
    assert appt.status == AppointmentStatus.PENDING  # re-opened for confirmation
    assert appt.scheduled_at == new_dt


@pytest.mark.asyncio
async def test_reschedule_pending_stays_pending(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    appt = await _make_appt(
        db, doctor, patient_user, default_clinic,
        AppointmentStatus.PENDING, days_ahead=1,
    )

    await patient_reschedule_appointment(
        db=db, user=patient_user, appointment_id=appt.id, new_datetime=_slot(4)
    )
    await db.refresh(appt)
    assert appt.status == AppointmentStatus.PENDING


@pytest.mark.asyncio
async def test_reschedule_rejected_for_completed(
    db, doctor, patient_user, default_clinic
):
    appt = await _make_appt(
        db, doctor, patient_user, default_clinic,
        AppointmentStatus.COMPLETED, days_ahead=1,
    )

    with pytest.raises(BadRequestError):
        await patient_reschedule_appointment(
            db=db, user=patient_user, appointment_id=appt.id, new_datetime=_slot(2)
        )
