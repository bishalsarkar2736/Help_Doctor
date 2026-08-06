from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import lazyload
from sqlalchemy.ext.asyncio import AsyncSession
import re
from app.core.time import UTC
from app.models.clinic import Clinic, ClinicStatus
from app.models.user import User
from app.schemas.clinic_hours_schema import (
    HolidayScheduleUpdate,
    OpeningHoursUpdate,
)
from app.schemas.clinic_schema import (
    ClinicUpdate,
    ClinicCreate,
    AdminClinicAssign,
)
from app.try_except.exceptions import (
    BadRequestError,NotFoundError
)
from sqlalchemy.exc import IntegrityError


async def get_clinic_by_id(
    db: AsyncSession,
    clinic_id: int,
) -> Clinic | None:

    # lazyload("*") scopes off Clinic's five lazy="selectin" relationships —
    # doctors, appointments, prescriptions, payments and admins — which loaded
    # the clinic's ENTIRE dataset on every call to this helper. It has 10+ call
    # sites, including the invitation and prescription paths.
    #
    # Still returns a real, mutable Clinic entity, which callers rely on
    # (clinic_service updates fields and soft-delete sets status/deleted_at).
    # Audited first: no code anywhere reads clinic.doctors / .appointments /
    # .prescriptions / .payments / .admins — only column attributes.
    result = await db.execute(
        select(Clinic)
        .options(lazyload("*"))
        .where(
            Clinic.id == clinic_id
        )
    )

    return result.scalar_one_or_none()


async def create_clinic(
    db: AsyncSession,
    payload: ClinicCreate,
) -> Clinic:
    # Normalize and validate name
    name = (payload.name or "").strip()

    if not name:
        raise BadRequestError("Clinic name is required")

    # Prevent duplicates (case-insensitive)
    existing = await db.execute(
        select(Clinic).where(
            func.lower(Clinic.name) == name.lower()
        )
    )

    if existing.scalar_one_or_none() is not None:
        raise BadRequestError("Clinic with this name already exists")

    clinic = Clinic(
        name=name,
        address=payload.address,
        phone=payload.phone,
        email=payload.email,
        website=payload.website,
        primary_color=payload.primary_color,
    )

    db.add(clinic)

    try:
        await db.flush()
    
    except IntegrityError:
        raise BadRequestError(
            "Clinic with this name already exists"
        )
    
    await db.refresh(clinic)

    return clinic


async def assign_clinic_to_admin(
    db: AsyncSession,
    payload: AdminClinicAssign,
) -> User:
    admin = await db.get(User, payload.admin_id)

    if admin is None:
        raise NotFoundError("Admin not found")

    if admin.role != "admin":
        raise BadRequestError("User is not an admin")

    clinic = await get_clinic_by_id(
        db=db,
        clinic_id=payload.clinic_id,
    )

    if clinic is None:
        raise NotFoundError("Clinic not found")

    admin.clinic_id = payload.clinic_id

    await db.flush()
    await db.refresh(admin)

    return admin


async def list_clinics(
    db: AsyncSession,
    status: ClinicStatus | None = None,
) -> list[Clinic]:
    """Platform-wide clinic list (super admin). Optional status filter."""
    query = select(Clinic).order_by(Clinic.id.desc())
    if status is not None:
        query = query.where(Clinic.status == status)
    result = await db.scalars(query)
    return list(result)


async def suspend_clinic(
    db: AsyncSession,
    clinic_id: int,
) -> Clinic:
    """Soft-suspend a clinic (platform action). Blocks its users from login."""
    clinic = await get_clinic_by_id(db, clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")

    if clinic.status == ClinicStatus.DELETED:
        raise BadRequestError("Clinic has been deleted")

    clinic.status = ClinicStatus.SUSPENDED
    clinic.suspended_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(clinic)
    return clinic


async def activate_clinic(
    db: AsyncSession,
    clinic_id: int,
) -> Clinic:
    """Reactivate a suspended clinic."""
    clinic = await get_clinic_by_id(db, clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")

    if clinic.status == ClinicStatus.DELETED:
        raise BadRequestError("Clinic has been deleted")

    clinic.status = ClinicStatus.ACTIVE
    clinic.suspended_at = None

    await db.flush()
    await db.refresh(clinic)
    return clinic


async def soft_delete_clinic(
    db: AsyncSession,
    clinic_id: int,
) -> Clinic:
    """Archive a clinic (soft delete — data is retained)."""
    clinic = await get_clinic_by_id(db, clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")

    clinic.status = ClinicStatus.DELETED
    clinic.deleted_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(clinic)
    return clinic


async def update_clinic(
    db: AsyncSession,
    clinic_id: int,
    payload: ClinicUpdate,
) -> Clinic:
    

    clinic = await get_clinic_by_id(
        db,
        clinic_id,
    )

    if clinic is None:
        raise NotFoundError(
            "Clinic not found"
        )
    
    HEX_COLOR_PATTERN = re.compile(
        r"^#(?:[0-9a-fA-F]{3}){1,2}$"
    )
    
    if (
        payload.primary_color
        and
        not HEX_COLOR_PATTERN.match(
            payload.primary_color
        )
    ):
        raise BadRequestError(
            "Invalid primary color"
        )

    

    clinic.name = payload.name
    clinic.address = payload.address
    clinic.phone = payload.phone
    clinic.email = payload.email
    clinic.website = payload.website
    clinic.primary_color = payload.primary_color
    if payload.timezone is not None:
        clinic.timezone = payload.timezone

    await db.flush()

    await db.refresh(clinic)

    return clinic

async def set_opening_hours(
    db: AsyncSession,
    clinic_id: int,
    payload: OpeningHoursUpdate,
) -> Clinic:
    """Replace the clinic's whole week of opening hours.

    A replace rather than a merge: with a partial update there is no way to say
    "we no longer open on Sunday", because an absent weekday and a removed one
    would look identical.

    The column is reassigned rather than mutated in place — SQLAlchemy tracks
    JSON columns by identity, so editing the existing dict leaves the change
    invisible to the session and it is silently never written.
    """
    clinic = await get_clinic_by_id(db, clinic_id)

    if clinic is None:
        raise NotFoundError("Clinic not found")

    clinic.opening_hours = payload.to_storage()

    await db.flush()
    await db.refresh(clinic)

    return clinic


async def set_holiday_schedule(
    db: AsyncSession,
    clinic_id: int,
    payload: HolidayScheduleUpdate,
) -> Clinic:
    """Replace the clinic's holiday closures. See set_opening_hours."""
    clinic = await get_clinic_by_id(db, clinic_id)

    if clinic is None:
        raise NotFoundError("Clinic not found")

    clinic.holiday_schedule = payload.to_storage()

    await db.flush()
    await db.refresh(clinic)

    return clinic
