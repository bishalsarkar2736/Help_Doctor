from fastapi import (
    APIRouter,
    Depends,
    Query,
    status
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import UserRole,User
from app.models.clinic import ClinicStatus

from app.security.rbac import (
    require_roles,
)

from app.schemas.clinic_schema import (
    ClinicResponse,
    ClinicUpdate,
    ClinicCreate,
    AdminClinicAssign,
)

from app.schemas.clinic_hours_schema import (
    HolidayScheduleUpdate,
    OpeningHoursUpdate,
)

from app.services.clinic_information_service import (
    get_clinic_holiday_schedule,
    get_clinic_opening_hours,
)

from app.services.clinic_service import (
    get_clinic_by_id,
    set_holiday_schedule,
    set_opening_hours,
    update_clinic,
    create_clinic,
    assign_clinic_to_admin,
    suspend_clinic,
    activate_clinic,
    soft_delete_clinic,
    list_clinics,
)
from app.try_except.exceptions import NotFoundError
from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic"],
)


# Separate plural router for the platform-wide clinics list (super admin).
clinics_router = APIRouter(
    prefix="/admin/clinics",
    tags=["Clinic"],
)


@clinics_router.get(
    "",
    response_model=list[ClinicResponse],
)
async def list_clinics_endpoint(
    status_filter: ClinicStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    return await list_clinics(db=db, status=status_filter)



@router.get(
    "",
    response_model=ClinicResponse,
)
async def get_clinic_settings(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    clinic = await get_clinic_by_id(
        db=db,
        clinic_id=resolved_clinic_id,
    )

    if clinic is None:
        raise NotFoundError(
            "Clinic not found"
        )

    return clinic




@router.post(
    "",
    response_model=ClinicResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_clinic_settings(
    payload: ClinicCreate,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.SUPER_ADMIN
        )
    ),
):

    clinic = await create_clinic(
        db=db,
        payload=payload,
    )

    return clinic



@router.put(
    "",
    response_model=ClinicResponse,
)
async def update_clinic_settings(
    clinic_id: int,
    payload: ClinicUpdate,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await update_clinic(
        db=db,
        clinic_id=resolved_clinic_id,
        payload=payload,
    )


@router.post(
    "/assign-admin",
    response_model=ClinicResponse,
)
async def assign_admin_clinic(
    payload: AdminClinicAssign,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    assigned_admin = await assign_clinic_to_admin(
        db=db,
        payload=payload,
    )

    if assigned_admin.clinic_id is None:
        raise NotFoundError("Clinic assignment failed")

    clinic = await get_clinic_by_id(
        db=db,
        clinic_id=assigned_admin.clinic_id,
    )

    if clinic is None:
        raise NotFoundError("Clinic not found")

    return clinic


# ---------------- CLINIC LIFECYCLE (SUPER ADMIN) ----------------

@router.post(
    "/{clinic_id}/suspend",
    response_model=ClinicResponse,
)
async def suspend_clinic_endpoint(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    return await suspend_clinic(db=db, clinic_id=clinic_id)


@router.post(
    "/{clinic_id}/activate",
    response_model=ClinicResponse,
)
async def activate_clinic_endpoint(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    return await activate_clinic(db=db, clinic_id=clinic_id)


@router.delete(
    "/{clinic_id}",
    response_model=ClinicResponse,
)
async def delete_clinic_endpoint(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    # Soft delete / archive — data is retained.
    return await soft_delete_clinic(db=db, clinic_id=clinic_id)


# ---------------------------------------------------------------------------
# Opening hours and holidays
#
# Separate endpoints rather than fields on ClinicUpdate. That schema requires
# `name` on every call, so folding hours into it would mean re-sending the
# clinic's identity to change a closing time — and any client that forgot would
# rename the clinic as a side effect.
# ---------------------------------------------------------------------------


async def _admin_clinic(db: AsyncSession, admin: User, clinic_id: int):
    """The clinic this admin is allowed to edit, or 404."""
    resolved = await resolve_clinic_id(db=db, user=admin, clinic_id=clinic_id)

    clinic = await get_clinic_by_id(db=db, clinic_id=resolved)

    if clinic is None:
        raise NotFoundError("Clinic not found")

    return clinic


@router.get("/opening-hours")
async def get_opening_hours_endpoint(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    clinic = await _admin_clinic(db, admin, clinic_id)

    return get_clinic_opening_hours(clinic)


@router.put("/opening-hours")
async def set_opening_hours_endpoint(
    clinic_id: int,
    payload: OpeningHoursUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Replace the whole week.

    A replace, not a merge: with a partial update there is no way to express
    "we no longer open on Sunday", since a removed day and an unmentioned one
    look the same.
    """
    clinic = await _admin_clinic(db, admin, clinic_id)

    await set_opening_hours(db=db, clinic_id=clinic.id, payload=payload)

    await db.commit()
    await db.refresh(clinic)

    return get_clinic_opening_hours(clinic)


@router.get("/holidays")
async def get_holidays_endpoint(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    clinic = await _admin_clinic(db, admin, clinic_id)

    return get_clinic_holiday_schedule(clinic)


@router.put("/holidays")
async def set_holidays_endpoint(
    clinic_id: int,
    payload: HolidayScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    clinic = await _admin_clinic(db, admin, clinic_id)

    await set_holiday_schedule(db=db, clinic_id=clinic.id, payload=payload)

    await db.commit()
    await db.refresh(clinic)

    return get_clinic_holiday_schedule(clinic)
