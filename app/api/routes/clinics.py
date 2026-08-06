from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.postgres import get_db
from app.domain.clinics.visibility import clinic_is_public
from app.models.clinic import Clinic, ClinicStatus
from app.schemas.clinic_schema import PublicClinic

# Public clinic directory (id + name), for patient-facing filters/booking.
router = APIRouter(prefix="/clinics", tags=["Clinic"])


@router.get("", response_model=list[PublicClinic])
async def list_public_clinics(
    db: AsyncSession = Depends(get_db),
):
    # PublicClinic exposes only id and name, but selecting the Clinic entity
    # pulled in its five lazy="selectin" relationships — every doctor,
    # appointment, prescription, payment and admin of every active clinic —
    # to render two fields. Measured at ~67ms with one clinic; it would grow
    # with the whole platform's data.
    result = await db.execute(
        select(Clinic.id, Clinic.name)
        # Shared predicate: this endpoint already filtered on status but not on
        # deleted_at, so a soft-deleted clinic still appeared in the picker.
        .where(*clinic_is_public())
        .order_by(Clinic.name)
    )
    return [PublicClinic(id=row.id, name=row.name) for row in result]
