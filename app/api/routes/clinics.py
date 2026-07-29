from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.postgres import get_db
from app.models.clinic import Clinic, ClinicStatus
from app.schemas.clinic_schema import PublicClinic

# Public clinic directory (id + name), for patient-facing filters/booking.
router = APIRouter(prefix="/clinics", tags=["Clinic"])


@router.get("", response_model=list[PublicClinic])
async def list_public_clinics(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Clinic)
        .where(Clinic.status == ClinicStatus.ACTIVE)
        .order_by(Clinic.name)
    )
    return list(result.scalars())
