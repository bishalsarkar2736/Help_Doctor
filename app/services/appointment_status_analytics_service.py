from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
)

from app.services.clinic_context_service import (
    get_current_clinic,
)


async def get_appointment_status_distribution(
    *,
    db: AsyncSession,
):
    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(
            Appointment.status.label(
                "status"
            ),
            func.count(
                Appointment.id
            ).label(
                "count"
            ),
        )
        .where(
            Appointment.clinic_id
            == clinic.id
        )
        .group_by(
            Appointment.status
        )
        .order_by(
            func.count(
                Appointment.id
            ).desc()
        )
    )

    rows = result.all()

    return [
        {
            "status": row.status.value
            if hasattr(
                row.status,
                "value",
            )
            else str(row.status),

            "count": row.count,
        }
        for row in rows
    ]