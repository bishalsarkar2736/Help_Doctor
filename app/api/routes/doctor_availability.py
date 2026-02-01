from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import time

from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.user import User

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


# Doctor creates slot
@router.post("/", response_model=AvailabilityOut)
async def add_availability(
    payload: AvailabilityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await create_availability(
        db,
        user,
        payload.day_of_week,
        payload.start_time,
        payload.end_time,
    )


# Public (patients)
@router.get("/{doctor_id}", response_model=list[AvailabilityOut])
async def get_doctor_availability(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await list_availability(db, doctor_id)


# Doctor: list own
@router.get("/", response_model=list[AvailabilityOut])
async def list_mine(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await list_my_availability(db, user)


# Doctor: update
@router.patch("/{availability_id}", response_model=AvailabilityOut)
async def update(
    availability_id: int,
    payload: AvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await update_availability(
        db,
        user,
        availability_id,
        payload.dict(),
    )


# Doctor: delete
@router.delete("/{availability_id}")
async def remove(
    availability_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await delete_availability(db, user, availability_id)
    return {"detail": "Deleted"}
