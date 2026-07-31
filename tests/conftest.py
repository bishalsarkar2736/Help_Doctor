from datetime import date
import os
import uuid
from urllib.parse import quote_plus

from app.config import get_settings

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
from app.models.user import User, UserRole,AuthProvider
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Patient
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
from app.core.constants import APPOINTMENT_DURATION_MINUTES


fastapi_app = create_app()
from app.db.postgres import get_db

import fakeredis

import app.db.redis
import app

# -----------------------------
# DATABASE


def _test_database_url() -> str:
    """Where the suite runs. Never a hardcoded credential.

    This file is committed, so a literal password in it is a published
    password — which is exactly how the previous one ended up in the
    repository history and had to be rotated.

    Instead the connection is derived from the application's OWN POSTGRES_*
    settings (pydantic reads them from the environment, or from .env locally),
    changing only the database name. That means one credential to manage rather
    than two, and it is the same server the app uses, so there is no second
    postgres install drifting out of sync. CI already exports POSTGRES_* for
    its ephemeral service container, so it works there unchanged.
    """
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit

    settings = get_settings()
    name = os.getenv("TEST_POSTGRES_DB", "helpdoctor_user_test")

    # reset_database() runs DROP SCHEMA public CASCADE on this database at the
    # start of the run. If it ever resolved to the application's database, a
    # test run would destroy live patient records. Refuse rather than trust the
    # environment to be right.
    #
    # CI is the one legitimate exception: its postgres is a service container
    # created for the job and thrown away with it, so the application database
    # and the test database are deliberately the same throwaway. That has to be
    # stated explicitly — never inferred — so this can't quietly pass on a
    # workstation where the same name means live data.
    same_name_allowed = os.getenv("TEST_DB_IS_DISPOSABLE") == "1"

    if name == settings.POSTGRES_DB and not same_name_allowed:
        raise RuntimeError(
            "Refusing to run: the test database name matches the application "
            f"database ({name!r}). reset_database() would drop its schema. "
            "Point TEST_POSTGRES_DB at a separate database, or — only if this "
            "postgres is disposable, as in CI — set TEST_DB_IS_DISPOSABLE=1."
        )

    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:"
        f"{quote_plus(settings.POSTGRES_PASSWORD)}@"
        f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{name}"
    )


TEST_DATABASE_URL = _test_database_url()



print("APP MODULE FILE:", app.__file__)

print("APP TYPE:", type(fastapi_app))


@pytest.fixture
def async_session_factory(engine):
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


async def reset_database():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    alembic_cfg = Config("alembic.ini")

    # Escape % for configparser, which reads it as interpolation syntax. The
    # URL is percent-encoded (a password containing @ or / would otherwise
    # break parsing), so a password like "pw$" arrives here as "pw%24" and
    # alembic raises "invalid interpolation syntax" without this. env.py does
    # the same thing for the same reason.
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        TEST_DATABASE_URL.replace("+asyncpg", "").replace("%", "%%"),
    )

    command.upgrade(
        alembic_cfg,
        "head",
    )

    await engine.dispose()


# @pytest_asyncio.fixture(scope="session")
# async def setup_database():

#     engine = create_async_engine(
#         TEST_DATABASE_URL,
#         echo=False,
#         poolclass=NullPool,
#     )

#     async with engine.begin() as conn:

#         await conn.execute(
#             text("DROP SCHEMA public CASCADE")
#         )

#         await conn.execute(
#             text("CREATE SCHEMA public")
#         )

#     alembic_cfg = Config("alembic.ini")

#     alembic_cfg.set_main_option(
#         "sqlalchemy.url",
#         TEST_DATABASE_URL.replace(
#             "+asyncpg",
#             "",
#         )
#     )

#     command.upgrade(
#         alembic_cfg,
#         "head",
#     )

#     await engine.dispose()

#     yield


@pytest_asyncio.fixture(scope="session")
async def setup_database():
    await reset_database()
    yield
    

@pytest_asyncio.fixture
async def isolated_database():
    await reset_database()

    yield

    await reset_database()


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


# @pytest_asyncio.fixture(autouse=True)
# async def clean_outbox(db):
#     await db.execute(delete(OutboxEvent))
#     await db.flush()
#     yield
            


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



@pytest_asyncio.fixture
async def outbox_event(db):
    event = OutboxEvent(
        event_type="TEST_EVENT",
        payload={},
    )

    db.add(event)
    await db.flush()
    await db.refresh(event)

    return event


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

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
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
async def admin_user(db: AsyncSession, default_clinic):
    user = User(
        email="admin@test.com",
        hashed_password="test-hash",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id = default_clinic.id,
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
    default_clinic,
):
    # 1️⃣ Create appointment in valid initial state
    appt = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
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
async def doctor(
    db: AsyncSession, 
    doctor_user: User,
    default_clinic,
):
    result = await db.execute(
        select(Doctor).where(Doctor.user_id == doctor_user.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=default_clinic.id,
        specialization="General Medicine",
        experience_years=5,
        bio="Test doctor",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.flush()

    return doctor


@pytest_asyncio.fixture
async def another_doctor(
    db: AsyncSession,
    default_clinic,
):
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
        clinic_id=default_clinic.id,
        specialization="Cardiology",
        experience_years=3,
        bio="Another test doctor",
        status=DoctorStatus.APPROVED,
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


# @pytest_asyncio.fixture
# async def outbox_event(db):
#     event = OutboxEvent(
#         event_type="APPOINTMENT_RESCHEDULED",
#         payload={
#             "user_id": 1,
#             "appointment_id": 1,
#         },
#     )
#     db.add(event)
#     await db.flush()
#     return event


def valid_slot(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC).replace(second=0, microsecond=0)

    minute = dt.minute - (dt.minute % APPOINTMENT_DURATION_MINUTES)

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
async def auth_doctor(
    db: AsyncSession,
    default_clinic,
):

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
        clinic_id=default_clinic.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
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

    patient = Patient(
        user_id=user.id,
        phone="01711111111",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
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
async def auth_admin(db, default_clinic):
    user = User(
        email="admin@test.com",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id=default_clinic.id,
    )

    db.add(user)
    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.ADMIN.value,
        }
    )

    return {
        "user": user,
        "headers": {
            "Authorization": f"Bearer {token}",
        },
    }


@pytest_asyncio.fixture
async def auth_super_admin(db):
    # Platform super admin: not bound to any clinic.
    user = User(
        email=f"superadmin-{uuid.uuid4()}@test.com",
        hashed_password="hash",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.SUPER_ADMIN.value,
        }
    )

    return {
        "user": user,
        "headers": {
            "Authorization": f"Bearer {token}",
        },
    }


@pytest_asyncio.fixture
async def auth_receptionist(db):

    user = User(
        email=f"receptionist-{uuid.uuid4()}@test.com",
        hashed_password="x",
        role=UserRole.RECEPTIONIST,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    token = create_access_token(
        data={
            "sub": str(user.id),
            "role": UserRole.RECEPTIONIST.value,
        }
    )

    return {
        "user": user,
        "headers": {
            "Authorization": f"Bearer {token}"
        },
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

#(autouse=True)
@pytest_asyncio.fixture
async def default_clinic(db):

    # Look up BY NAME, not "any clinic". `select(Clinic)` with no filter
    # returns an arbitrary row, so as soon as a test also builds a second
    # clinic this fixture could hand back that one — putting the "two" tenants
    # in the same clinic and making cross-tenant isolation tests silently
    # assert nothing.
    clinic = await db.scalar(
        select(Clinic).where(Clinic.name == "Test Clinic")
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


@pytest_asyncio.fixture
async def google_user(db):

    user = User(
        email="google@test.com",
        hashed_password=None,
        google_id="google-123",
        auth_provider=AuthProvider.GOOGLE,
        role=UserRole.PATIENT,
        is_active=True,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user

# ---------------------------------------------------------------------------
# Second clinic — the fixtures cross-tenant isolation tests need.
#
# Every existing fixture hangs off `default_clinic`, so nothing in the suite
# could previously express "clinic A must not see clinic B". These build a
# genuinely separate tenant: its own clinic row, its own admin and doctor, and
# its own patient with a real treatment relationship inside that clinic.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def second_clinic(db):
    clinic = Clinic(
        name="Second Clinic",
        address="Chattogram",
        phone="01800000000",
        email=f"second-{uuid.uuid4()}@test.com",
        website="https://second.test",
        primary_color="#0F766E",
    )
    db.add(clinic)
    await db.flush()
    await db.refresh(clinic)
    return clinic


@pytest_asyncio.fixture
async def other_clinic_admin(db, second_clinic):
    user = User(
        email=f"admin-b-{uuid.uuid4()}@test.com",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
        clinic_id=second_clinic.id,
    )
    db.add(user)
    await db.flush()

    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.ADMIN.value}
    )
    return {
        "user": user,
        "clinic": second_clinic,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def other_clinic_doctor(db, second_clinic):
    user = User(
        email=f"doctor-b-{uuid.uuid4()}@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=second_clinic.id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=second_clinic.id,
        specialization="Dermatology",
        experience_years=4,
        bio="Doctor at the second clinic",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.DOCTOR.value}
    )
    return {
        "user": user,
        "doctor": doctor,
        "clinic": second_clinic,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def other_clinic_patient(db, second_clinic, other_clinic_doctor):
    """A patient of clinic B, with an appointment there.

    The appointment matters: it gives clinic B's doctor a legitimate treatment
    relationship, so a cross-tenant test is comparing "allowed in my clinic"
    against "denied in yours" rather than two flavours of denial.
    """

    user = User(
        email=f"patient-b-{uuid.uuid4()}@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        Patient(
            user_id=user.id,
            phone="01900000000",
            address="Chattogram",
            date_of_birth=date(1992, 3, 4),
            gender="FEMALE",
            allergies="Penicillin",
        )
    )

    db.add(
        Appointment(
            patient_id=user.id,
            doctor_id=other_clinic_doctor["doctor"].id,
            clinic_id=second_clinic.id,
            consultation_fee=400,
            scheduled_at=utc_now(),
            status=AppointmentStatus.COMPLETED,
            completed_at=utc_now(),
        )
    )
    await db.flush()
    return user
