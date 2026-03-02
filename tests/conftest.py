
import asyncio
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
from app.db.base import Base
from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor_availability import DoctorAvailability
from app.domain.fsm.appointment_transition import transition_appointment
from alembic import command
from alembic.config import Config
from sqlalchemy import text

# -----------------------------
# DATABASE
TEST_DATABASE_URL = "postgresql+asyncpg://helpdoctor:helpdoctor$@localhost/helpdoctor_user_test"





# engine = create_async_engine(
#     TEST_DATABASE_URL,
#     echo=False,
#     poolclass=NullPool,
#     future=True,
# )

@pytest.fixture
def async_session_factory(engine):
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )




@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # 1️⃣ Reset schema
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    # 2️⃣ Configure Alembic to use TEST DB
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        TEST_DATABASE_URL.replace("+asyncpg", "")
    )

    # 3️⃣ Run migrations
    command.upgrade(alembic_cfg, "head")

    yield engine

    await engine.dispose()



# @pytest_asyncio.fixture
# async def db() -> AsyncSession:
#     async with engine.connect() as conn:
#         # start outer transaction
#         trans = await conn.begin()

#         session = AsyncSession(
#             bind=conn,
#             expire_on_commit=False,
#         )

#         try:
#             yield session
#         finally:
#             await session.close()
#             await trans.rollback()




@pytest_asyncio.fixture
async def db(engine):
    async with engine.connect() as conn:
        trans = await conn.begin()

        async_session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
        )

        await async_session.begin_nested()

        @event.listens_for(async_session.sync_session, "after_transaction_end")
        def restart_savepoint(session, transaction):
            if transaction.nested and not transaction._parent.nested:
                session.begin_nested()

        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()
            



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


# @pytest_asyncio.fixture
# async def doctor_user(db: AsyncSession):
#     user = User(
#         email="doctor@test.com",
#         hashed_password="test-hash",
#         role=UserRole.DOCTOR,
#         is_active=True,
#     )
#     db.add(user)
#     await db.flush()

#     doctor = Doctor(
#         user_id=user.id,
#         specialization="General Medicine",
#         experience_years=5,
#         bio="Test doctor",
#         is_verified=True,
#     )
#     db.add(doctor)
#     await db.flush()
#     await db.refresh(doctor)

#     return doctor

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
    #await db.refresh(user)

    return user  # ✅ RETURN USER, NOT DOCTOR

# @pytest_asyncio.fixture
# async def doctor_user(db: AsyncSession):
#     user = User(
#         email="doctor@test.com",
#         hashed_password="test-hash",
#         role=UserRole.DOCTOR,
#         is_active=True,
#     )

#     db.add(user)
#     await db.flush()

#     doctor = Doctor(
#         user_id=user.id,
#         specialization="General Medicine",
#         experience_years=5,
#         bio="Test doctor",
#         is_verified=True,
#     )

#     db.add(doctor)
#     await db.flush()

#     return user




# -----------------------------
# APPOINTMENTS
# -----------------------------

@pytest_asyncio.fixture
# async def appointment(
#     db: AsyncSession,
#     doctor_user: Doctor,
#     patient_user: User,
# ):
async def appointment(
    db: AsyncSession,
    doctor: Doctor,
    patient_user: User,
):
    appt = Appointment(
        #doctor_id=doctor_user.id,
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )
    db.add(appt)
    await db.flush()
    await db.refresh(appt)
    return appt


# @pytest_asyncio.fixture
# async def cancelled_appointment(
#     db: AsyncSession,
#     #doctor_user: Doctor,
#     doctor: Doctor,
#     patient_user: User,
#     admin_user: User,
# ):
#     appt = Appointment(
#         #doctor_id=doctor_user.id,
#         doctor_id=doctor.id,
#         patient_id=patient_user.id,
#         scheduled_at=datetime.now(timezone.utc) - timedelta(days=1),
#         status=AppointmentStatus.CANCELLED,
#         cancelled_by=admin_user.id,
#         cancelled_at=datetime.now(timezone.utc),
#         cancel_reason="Test cancel",
#     )
#     db.add(appt)
#     await db.flush()
#     await db.refresh(appt)
#     return appt

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


