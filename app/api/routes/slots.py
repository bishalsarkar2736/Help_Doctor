from fastapi import APIRouter, Query, Depends
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.slot_service import get_doctor_slots
from app.db.postgres import get_db

router = APIRouter(prefix="/slots", tags=["Slots"])


@router.get("/doctors/{doctor_id}/slots")
async def list_slots(
    doctor_id: int,
    start_date: date = Query(...),
    days: int = Query(1, ge=1, le=7),
    only_available: bool = Query(False),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    return await get_doctor_slots(
        db=db,
        doctor_id=doctor_id,
        start_date=start_date,
        days=days,
        only_available=only_available,
        limit=limit,
        offset=offset,
    )