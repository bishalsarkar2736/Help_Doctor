from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.user import User, UserRole

from app.schemas.doctor_availability import (
    AvailabilityCreate,
    AvailabilityUpdate,
    AvailabilityOut,
)

from app.services.doctor_availability_service import (
    create_availability,
    list_availability,
    list_my_availability,
    update_availability,
    delete_availability,
)

router = APIRouter(
    prefix="/doctors/availability",
    tags=["Doctor Availability"],
)


# ✅ Doctor creates availability
@router.post("/", response_model=AvailabilityOut)
async def add_availability(
    payload: AvailabilityCreate,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await create_availability(
        db,
        doctor,
        payload.day_of_week,
        payload.start_time,
        payload.end_time,
    )


# ✅ Public endpoint (patients can view)
@router.get("/{doctor_id}", response_model=list[AvailabilityOut])
async def get_doctor_availability(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await list_availability(db, doctor_id)


# ✅ Doctor: view own availability
@router.get("/", response_model=list[AvailabilityOut])
async def list_mine(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await list_my_availability(db, doctor)


# ✅ Doctor: update availability
@router.patch("/{availability_id}", response_model=AvailabilityOut)
async def update(
    availability_id: int,
    payload: AvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    return await update_availability(
        db,
        doctor,
        availability_id,
        payload.dict(exclude_unset=True),
    )


# ✅ Doctor: delete availability
@router.delete("/{availability_id}")
async def remove(
    availability_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    await delete_availability(db, doctor, availability_id)
    return {"detail": "Deleted"}