from sqlalchemy.ext.asyncio import AsyncSession


async def get_current_clinic(
    db: AsyncSession,
):
    raise RuntimeError(
        "get_current_clinic() is deprecated. "
        "Use doctor.clinic_id or explicit clinic_id."
    )