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
    ClinicSubdomainUpdate,
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


# Which unique index a duplicate hit, and what to tell the caller.
#
# Every IntegrityError here used to be reported as "Clinic with this name
# already exists". With a second unique index on the table that answer is
# sometimes simply wrong: a caller who reused a subdomain was told to change
# the name, which does not fix anything.
#
# asyncpg reports the INDEX name in constraint_name for a unique-index
# violation, so the two are distinguishable.
_DUPLICATE_MESSAGES = {
    "uq_clinic_name_lower": "Clinic with this name already exists",
    "uq_clinic_subdomain_lower": "Clinic with this subdomain already exists",
}


def _violated_constraint(error: IntegrityError) -> str | None:
    """The constraint/index name the database reported, if it gave one."""
    # SQLAlchemy wraps the driver error, which in turn wraps asyncpg's.
    candidate = error.orig

    for _ in range(3):
        name = getattr(candidate, "constraint_name", None)

        if name:
            return name

        candidate = getattr(candidate, "__cause__", None)

        if candidate is None:
            break

    return None


async def _subdomain_taken(
    db: AsyncSession,
    subdomain: str,
    exclude_clinic_id: int | None = None,
) -> bool:
    """Whether another clinic already holds this subdomain, case-insensitively.

    `exclude_clinic_id` keeps a clinic from colliding with itself: re-sending
    the subdomain a clinic already has is a no-op, not a duplicate.
    """
    query = select(Clinic).where(
        func.lower(Clinic.subdomain) == subdomain.lower()
    )

    if exclude_clinic_id is not None:
        query = query.where(Clinic.id != exclude_clinic_id)

    existing = await db.execute(query)

    return existing.scalar_one_or_none() is not None


def _duplicate_error(error: IntegrityError) -> BadRequestError:
    """Translate a known duplicate into a 400, or re-raise.

    Anything that is not one of this table's unique indexes — a check
    constraint, a NOT NULL, a foreign key — is a bug rather than bad user
    input, and must not be flattened into a 400 that tells the caller to change
    their name. Those propagate.
    """
    message = _DUPLICATE_MESSAGES.get(_violated_constraint(error) or "")

    if message is None:
        raise error

    return BadRequestError(message)


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

    # Already stripped, lowercased and format-checked by ClinicCreate; None
    # when the clinic has no hostname yet, which is the normal case.
    subdomain = payload.subdomain

    # The same courtesy pre-check the name gets: a clear message instead of a
    # constraint error. It is NOT the guarantee — two concurrent requests can
    # both pass this — and uq_clinic_subdomain_lower below is what actually
    # holds. Comparing with LOWER() so it agrees with that index.
    if subdomain is not None and await _subdomain_taken(db, subdomain):
        raise BadRequestError("Clinic with this subdomain already exists")

    clinic = Clinic(
        name=name,
        subdomain=subdomain,
        address=payload.address,
        phone=payload.phone,
        email=payload.email,
        website=payload.website,
        primary_color=payload.primary_color,
    )

    db.add(clinic)

    try:
        await db.flush()

    except IntegrityError as error:
        raise _duplicate_error(error)
    
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


async def set_clinic_subdomain(
    db: AsyncSession,
    clinic_id: int,
    payload: ClinicSubdomainUpdate,
) -> Clinic:
    """Assign, change or clear a clinic's subdomain.

    Separate from update_clinic for the reason the opening-hours endpoints are
    separate (admin_clinic.py): that schema assigns every field it carries, so
    a client omitting the subdomain would delete it. Here the field is required
    by ClinicSubdomainUpdate, so omitting it is a 422 and clearing it is an
    explicit `null` — the distinction this function depends on.

    CLEARING IS ALLOWED, deliberately. A subdomain is a public identity and
    the codebase treats those cautiously — clinics are soft-deleted, users are
    never hard-deleted — but a mistyped hostname has to be correctable, and
    this endpoint is already restricted to the platform operator who can
    suspend or archive the whole clinic.

    What it does NOT do is protect a released subdomain from being taken by
    another clinic. Reassigning one means URLs issued for the old tenant would
    reach the new one, which is a cross-tenant confusion rather than merely a
    broken link. Nothing routes on this column yet, so that hazard is not live;
    a retired-subdomains table is the fix when it becomes so.
    """
    clinic = await get_clinic_by_id(db, clinic_id)

    if clinic is None:
        raise NotFoundError("Clinic not found")

    # Already stripped, lowercased, format-checked and screened against the
    # reserved list by ClinicSubdomainUpdate.
    subdomain = payload.subdomain

    # Courtesy pre-check, as in create_clinic. uq_clinic_subdomain_lower below
    # is the guarantee; this only produces a better message.
    if subdomain is not None and await _subdomain_taken(
        db, subdomain, exclude_clinic_id=clinic.id
    ):
        raise BadRequestError("Clinic with this subdomain already exists")

    clinic.subdomain = subdomain

    try:
        await db.flush()

    except IntegrityError as error:
        raise _duplicate_error(error)

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
