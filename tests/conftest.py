import pytest
import pytest_asyncio
from datetime import datetime, timedelta,timezone

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.user import User, UserRole
from app.models.appointment import Appointment, AppointmentStatus


# -----------------------------
# DATABASE
# -----------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# -----------------------------
# USERS
# -----------------------------

@pytest.fixture
async def user(db):
    user = User(
        email="user@test.com",
        hashed_password="test-password-hash",
        role=UserRole.PATIENT,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@pytest.fixture
async def admin_user(db):
    admin = User(
        email="admin@test.com",
        hashed_password="test-password-hash",
        role=UserRole.ADMIN,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


@pytest.fixture
async def doctor_user(db):
    doctor = User(
        email="doctor@test.com",
        role=UserRole.DOCTOR,
        hashed_password="test-password-hash"

    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


@pytest.fixture
async def patient_user(db):
    patient = User(
        email="patient@test.com",
        role=UserRole.PATIENT,
        hashed_password="test-password-hash"

    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


# -----------------------------
# APPOINTMENTS
# -----------------------------

@pytest.fixture
async def appointment(
    db: AsyncSession,
    doctor_user: User,
    patient_user: User,
):
    appointment = Appointment(
        doctor_id=doctor_user.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)
    return appointment


@pytest.fixture
async def cancelled_appointment(
    db: AsyncSession,
    doctor_user: User,
    patient_user: User,
    admin_user: User,
):
    appointment = Appointment(
        doctor_id=doctor_user.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(days=1),
        status=AppointmentStatus.CANCELLED,
        cancelled_by=admin_user.id,
        cancelled_at=datetime.now(timezone.utc)
,
        cancel_reason="Test cancel",
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)
    return appointment
