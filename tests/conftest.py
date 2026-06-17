import os
import uuid

os.environ["TESTING"] = "1"
os.environ["OTEL_SDK_DISABLED"] = "true"

from datetime import datetime, timedelta, timezone, time
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool
from sqlalchemy import event,select
from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor_availability import DoctorAvailability
from app.domain.fsm.appointment_transition import transition_appointment
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.core.time import UTC,utc_now
from app.models.outbox_event import OutboxEvent
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from fastapi.testclient import TestClient
from app.security.jwt import create_access_token

from app.models.prescription import (
    Prescription,
    PrescriptionStatus,
    PrescriptionItem,
)
from app.models.clinic import Clinic



fastapi_app = create_app()
from app.db.postgres import get_db

import fakeredis

import app.db.redis
import app

# -----------------------------
# DATABASE
TEST_DATABASE_URL = "postgresql+asyncpg://helpdoctor:helpdoctor$@localhost/helpdoctor_user_test"



print("APP MODULE FILE:", app.__file__)

print("APP TYPE:", type(fastapi_app))


@pytest.fixture
def async_session_factory(engine):
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

@pytest_asyncio.fixture(scope="session")
async def setup_database():

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    async with engine.begin() as conn:

        await conn.execute(
            text("DROP SCHEMA public CASCADE")
        )

        await conn.execute(
            text("CREATE SCHEMA public")
        )

    alembic_cfg = Config("alembic.ini")

    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        TEST_DATABASE_URL.replace(
            "+asyncpg",
            "",
        )
    )

    command.upgrade(
        alembic_cfg,
        "head",
    )

    await engine.dispose()

    yield


@pytest_asyncio.fixture
async def engine(setup_database):

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):

    async with engine.connect() as connection:

        transaction = await connection.begin()

        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
        )

        nested = await connection.begin_nested()

        @event.listens_for(
            session.sync_session,
            "after_transaction_end",
        )
        def restart_savepoint(session_, transaction_):

            nonlocal nested

            if not nested.is_active:
                nested = connection.sync_connection.begin_nested()

        try:
            yield session

        finally:
            await session.close()
            await transaction.rollback()
            


@pytest_asyncio.fixture
async def client(db):

    async def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(
        app=fastapi_app,
        raise_app_exceptions=True
    )

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac

    #fastapi_app.dependency_overrides.clear()
    del fastapi_app.dependency_overrides[get_db]




# ---------------------------
# Fake Redis for ALL tests
# ---------------------------

@pytest_asyncio.fixture(autouse=True)
async def fake_redis(monkeypatch):

    fake = fakeredis.FakeAsyncRedis()

    async def _get_redis():
        return fake

    # patch redis dependency
    monkeypatch.setattr(app.db.redis, "get_redis", _get_redis)

    # patch already-created redis client
    #monkeypatch.setattr(app.db.redis, "redis_client", fake)

    yield fake

    await fake.flushall()

    await fake.aclose()


# USER

@pytest_asyncio.fixture
async def user(db: AsyncSession):
    user = User(
        email="user@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user


@pytest_asyncio.fixture
async def patient_user(db: AsyncSession):
    user = User(
        email="patient@test.com",
        hashed_password="test-hash",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user


@pytest_asyncio.fixture
async def another_patient_user(db: AsyncSession):
    user = User(
        email="another_patient@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession):
    user = User(
        email="admin@test.com",
        hashed_password="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user




@pytest_asyncio.fixture
async def doctor_user(db: AsyncSession):
    user = User(
        email="doctor@test.com",
        hashed_password="test-hash",
        role=UserRole.DOCTOR,
        is_active=True,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user  # ✅ RETURN USER, NOT DOCTOR






# -----------------------------
# APPOINTMENTS
# -----------------------------

@pytest_asyncio.fixture
async def appointment(
    db: AsyncSession,
    doctor: Doctor,
    patient_user: User,
    default_clinic,
):
    appt = Appointment(
        #doctor_id=doctor_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )
    db.add(appt)
    await db.flush()
    await db.refresh(appt)
    return appt



@pytest_asyncio.fixture
async def cancelled_appointment(
    db: AsyncSession,
    doctor: Doctor,
    patient_user: User,
    admin_user: User,
):
    # 1️⃣ Create appointment in valid initial state
    appt = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )

    db.add(appt)
    await db.flush()

    # 2️⃣ Transition properly using FSM
    await transition_appointment(
        db=db,
        appointment=appt,
        new_status=AppointmentStatus.CANCELLED,
        changed_by=admin_user.id,
    )

    await db.flush()
    await db.refresh(appt)

    return appt


#DOCTOR

@pytest_asyncio.fixture
async def doctor(db: AsyncSession, doctor_user: User):
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == doctor_user.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    doctor = Doctor(
        user_id=doctor_user.id,
        specialization="General Medicine",
        experience_years=5,
        bio="Test doctor",
        is_verified=True,
    )

    db.add(doctor)
    await db.flush()

    return doctor


@pytest_asyncio.fixture
async def another_doctor(db: AsyncSession):
    # create separate user first
    another_user = User(
        email="another_doctor@test.com",
        hashed_password="hashed",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(another_user)
    await db.flush()

    # create doctor profile
    another_doctor = Doctor(
        user_id=another_user.id,
        specialization="Cardiology",
        experience_years=3,
        bio="Another test doctor",
        is_verified=True,
    )
    db.add(another_doctor)
    await db.flush()
    await db.refresh(another_doctor)

    return another_doctor





@pytest_asyncio.fixture
async def doctor_availability(db: AsyncSession, doctor: Doctor):
    items = []

    for day in range(7):
        availability = DoctorAvailability(
            doctor_id=doctor.id,
            day_of_week=day,
            start_time=time(0, 0),
            end_time=time(23, 59),
            is_available=True,
        )
        db.add(availability)
        items.append(availability)

    await db.flush()
    return items


@pytest_asyncio.fixture
async def outbox_event(db):
    event = OutboxEvent(
        event_type="APPOINTMENT_RESCHEDULED",
        payload={
            "user_id": 1,
            "appointment_id": 1,
        },
    )
    db.add(event)
    await db.flush()
    return event

def valid_slot(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC).replace(second=0, microsecond=0)
    minute = 0 if dt.minute < 30 else 30
    return dt.replace(minute=minute)


@pytest.fixture
def ws_client():

    with TestClient(fastapi_app) as client:
        yield client



@pytest_asyncio.fixture
async def appointment_factory(db):

    async def factory(
        *,
        patient_id,
        doctor_id,
        status,
    ):
        
        clinic = await db.scalar(
            select(Clinic)
        )

        appointment = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_id,
            status=status,
            scheduled_at=utc_now(),
            clinic_id=clinic.id,
        )

        db.add(appointment)

        await db.flush()

        return appointment

    return factory


@pytest_asyncio.fixture
async def prescription_factory(db, appointment_factory):

    async def factory(
        *,
        doctor_id,
        patient_id,
        appointment_id=None,
        status=PrescriptionStatus.DRAFT,
        appointment_status=AppointmentStatus.IN_CONSULTATION,
        notes="Test prescription",
        issued_at=None,
        with_items=True,
        revision_number=1,
        is_latest_revision=True,
        parent_prescription_id=None,
    ):
        
        clinic = await db.scalar(
            select(Clinic)
        )

        # ====================================
        # AUTO CREATE APPOINTMENT (SAFE DEFAULT)
        # ====================================
        if appointment_id is None:

            appointment = await appointment_factory(
                patient_id=patient_id,
                doctor_id=doctor_id,
                status=appointment_status,
            )

            appointment_id = appointment.id

        prescription = Prescription(
            appointment_id=appointment_id,
            doctor_id=doctor_id,
            patient_id=patient_id,
            status=status,
            notes=notes,
            issued_at=issued_at,
            parent_prescription_id=parent_prescription_id,
            revision_number=revision_number,
            is_latest_revision=is_latest_revision,
            clinic_id=clinic.id,
        )

        db.add(prescription)
        await db.flush()

        if with_items:
            db.add(
                PrescriptionItem(
                    prescription_id=prescription.id,
                    medicine_name="Napa",
                    dosage="500mg",
                    frequency="2 times daily",
                    duration_days=5,
                    instructions="After meal",
                )
            )
            await db.flush()

        return prescription

    return factory

@pytest_asyncio.fixture
async def issued_prescription(
    db,
    doctor,
    patient_user,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.ISSUED,
        issued_at=utc_now(),   # FIX
    )

    await db.flush()
    await db.refresh(prescription)
    return prescription



@pytest_asyncio.fixture
async def auth_doctor(db: AsyncSession):

    user = User(
        email="doctor@test.com",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )

    db.add(user)

    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        is_verified=True,
    )

    db.add(doctor)

    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.DOCTOR.value,
        }
    )

    return {
        "user": user,
        "doctor": doctor,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
    }


@pytest_asyncio.fixture
async def auth_patient(db):

    user = User(
        email=f"patient-{uuid.uuid4()}@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(user)

    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.PATIENT.value,
        }
    )

    return {
        "user": user,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
    }


@pytest_asyncio.fixture
async def auth_another_patient(db):

    user = User(
        email=f"another-{uuid.uuid4()}@test.com",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(user)

    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.PATIENT.value,
        }
    )

    return {
        "user": user,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
    }


@pytest_asyncio.fixture
async def auth_another_doctor(another_doctor):
    token = create_access_token({
        "sub": str(another_doctor.user_id),
        "role": UserRole.DOCTOR.value,
    })

    return {
        "user": another_doctor.user,
        "doctor": another_doctor,
        "headers": {
            "Authorization": f"Bearer {token}"
        }
    }


@pytest_asyncio.fixture
async def draft_prescription(
    db,
    doctor,
    patient_user,
    appointment_factory,
    prescription_factory,
):
    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.COMPLETED,
    )

    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        status=PrescriptionStatus.DRAFT,
    )

    await db.flush()
    await db.refresh(prescription)

    return prescription



@pytest_asyncio.fixture
async def issued_prescription_event(
    db,
    issued_prescription,
):

    now = datetime.now(UTC).isoformat()

    event = OutboxEvent(
        event_type="PRESCRIPTION_ISSUED",
        payload={
            "schema_version": 1,
            "occurred_at": now,
            "aggregate_type": "prescription",
            "aggregate_id":
                issued_prescription.id,

            "correlation_id": None,
            "causation_id": None,

            "actor": {
                "id": 1,
                "role": "DOCTOR",
            },

            "event_type":
                "PRESCRIPTION_ISSUED",
            "prescription_id":
                issued_prescription.id,
            "appointment_id":
                issued_prescription.appointment_id,
            "patient_id":
                issued_prescription.patient_id,
            "doctor_id":
                issued_prescription.doctor_id,
            "issued_at": now,
        },
        status="pending",
    )

    db.add(event)

    await db.flush()
    await db.refresh(event)

    return event


@pytest_asyncio.fixture
async def prescription_updated_event(
    db,
    issued_prescription,
):

    now = datetime.now(UTC).isoformat()

    event = OutboxEvent(
        event_type="PRESCRIPTION_UPDATED",
        payload={
            "schema_version": 1,
            "occurred_at": now,
            "aggregate_type":
                "prescription",
            "aggregate_id":
                issued_prescription.id,

            "correlation_id": None,
            "causation_id": None,

            "actor": {
                "id": 1,
                "role": "DOCTOR",
            },

            "event_type":
                "PRESCRIPTION_UPDATED",
            "prescription_id":
                issued_prescription.id,
            "appointment_id":
                issued_prescription.appointment_id,
            "patient_id":
                issued_prescription.patient_id,
            "doctor_id":
                issued_prescription.doctor_id,
        },
        status="pending",
    )

    db.add(event)

    await db.flush()
    await db.refresh(event)

    return event


@pytest_asyncio.fixture(autouse=True)
async def default_clinic(db):

    clinic = await db.scalar(
        select(Clinic)
    )

    if clinic is None:
        clinic = Clinic(
            name="Test Clinic",
            address="Dhaka",
            phone="01700000000",
            email="clinic@test.com",
            website="https://test.com",
            primary_color="#2563EB",
        )

        db.add(clinic)

        await db.flush()
        await db.refresh(clinic)

    return clinic