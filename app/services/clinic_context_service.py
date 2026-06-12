from sqlalchemy.ext.asyncio import AsyncSession

from app.services.clinic_service import (
    get_clinic,
)


async def get_current_clinic(
    db: AsyncSession,
):
    return await get_clinic(db)