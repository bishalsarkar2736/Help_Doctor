import asyncio
import pytest
from datetime import datetime, timezone,timedelta
from sqlalchemy.exc import IntegrityError,DBAPIError
from app.models.appointment import Appointment
from sqlalchemy import select, func
from app.models.doctor import Doctor
from app.models.user import User,UserRole
from app.services.appointment_service import book_appointment
from app.try_except.exceptions import BadRequestError
from app.models.doctor_availability import DoctorAvailability
from datetime import time


@pytest.mark.asyncio
async def test_doctor_overlap_is_prevented_under_concurrency(
    async_session_factory,
):
    async with async_session_factory() as session:
        patient = User(
            email="concurrency@test.com",
            hashed_password="x",
            role=UserRole.PATIENT,
            is_active=True,
        )

        doctor_owner = User(
            email="doc@test.com",
            hashed_password="x",
            role=UserRole.DOCTOR,
            is_active=True,
        )

        session.add_all([patient, doctor_owner])
        await session.flush()

        doctor = Doctor(
            user_id=doctor_owner.id,
            specialization="General",
            experience_years=5,
            bio="Test",
            is_verified=True,
        )

        session.add(doctor)
        await session.flush()

        start = datetime.now(timezone.utc) + timedelta(days=1)
        start = start.replace(hour=10, minute=0, second=0, microsecond=0)

        day = start.weekday()

        availability = DoctorAvailability(
            doctor_id=doctor.id,
            day_of_week=day,   # match booking day
            start_time=time(0, 0),
            end_time=time(23, 59),
            is_available=True,
        )

        session.add(availability)   
        await session.commit()      

        doctor_id = doctor.id
        patient_id = patient.id


    async def create_appointment():
        async with async_session_factory() as session:
            try:
                patient_obj = await session.get(User, patient_id)

                await book_appointment(
                    db=session,
                    patient=patient_obj,   
                    doctor_id=doctor_id,
                    scheduled_at=start,
                )

                await session.commit()
                return "success"

            except (BadRequestError, IntegrityError, DBAPIError):
                await session.rollback()
                return "error"


    # 🔥 THIS WAS MISSING
    results = await asyncio.gather(
        create_appointment(),
        create_appointment(),
    )

    # Better assertion
    assert results.count("success") == 1
    assert results.count("error") == 1




    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Appointment)
        )

    assert count == 1


    