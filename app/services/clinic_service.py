from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re
from app.models.clinic import Clinic
from app.schemas.clinic_schema import ClinicUpdate
from app.try_except.exceptions import (
    BadRequestError,
)

async def get_clinic(
    db: AsyncSession,
) -> Clinic | None:

    result = await db.execute(
        select(Clinic)
        .limit(1)
    )

    return result.scalar_one_or_none()


async def update_clinic(
    db: AsyncSession,
    payload: ClinicUpdate,
) -> Clinic:
    
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

    clinic = await get_clinic(db)

    if clinic is None:

        clinic = Clinic(
            name=payload.name,
            address=payload.address,
            phone=payload.phone,
            email=payload.email,
            website=payload.website,
            primary_color=payload.primary_color,
        )

        db.add(clinic)

    else:

        clinic.name = payload.name
        clinic.address = payload.address
        clinic.phone = payload.phone
        clinic.email = payload.email
        clinic.website = payload.website
        clinic.primary_color = payload.primary_color

    await db.flush()

    await db.refresh(clinic)

    return clinic