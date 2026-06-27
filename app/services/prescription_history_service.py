from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription import (
    Prescription,
)

from app.try_except.exceptions import (
    NotFoundError,
)


async def get_prescription_revision_history(
    *,
    db: AsyncSession,
    prescription_id: int,
    clinic_id: int,
):



    # Get root prescription safely
    root = await db.scalar(
        select(Prescription)
        .where(
            Prescription.id
            == prescription_id,

            Prescription.clinic_id
            == clinic_id,
        )
    )

    if not root:
        raise NotFoundError(
            "Prescription not found"
        )

    root_id = (
        root.parent_prescription_id
        or root.id
    )

    result = await db.execute(
        select(Prescription)
        .where(
            (
                Prescription.id
                == root_id
            )
            |
            (
                Prescription.parent_prescription_id
                == root_id
            ),

            Prescription.clinic_id
            == clinic_id,
        )
        .order_by(
            Prescription.revision_number.asc()
        )
    )

    revisions = result.scalars().all()

    return revisions