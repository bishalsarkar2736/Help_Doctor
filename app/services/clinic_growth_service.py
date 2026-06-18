from datetime import date

from dateutil.relativedelta import relativedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment
from app.models.patient import Patient

from app.services.clinic_context_service import (
    get_current_clinic,
)

from app.services.revenue_analytics_service import (
    get_monthly_revenue,
)




async def get_monthly_patient_growth(
    *,
    db: AsyncSession,
    months: int = 12,
):
    clinic = await get_current_clinic(db)

    start_date = (
        date.today().replace(day=1)
        - relativedelta(months=months - 1)
    )

    result = await db.execute(
        select(
            func.to_char(
                Patient.created_at,
                "YYYY-MM",
            ).label("month"),

            func.count(
                Patient.id
            ).label("count"),
        )
        .where(
            Patient.clinic_id
            == clinic.id,

            Patient.created_at
            >= start_date,
        )
        .group_by("month")
        .order_by("month")
    )

    rows = result.all()

    return [
        {
            "month": row.month,
            "count": row.count,
        }
        for row in rows
    ]



async def get_monthly_appointment_growth(
    *,
    db: AsyncSession,
    months: int = 12,
):
    clinic = await get_current_clinic(db)

    start_date = (
        date.today().replace(day=1)
        - relativedelta(months=months - 1)
    )

    result = await db.execute(
        select(
            func.to_char(
                Appointment.created_at,
                "YYYY-MM",
            ).label("month"),

            func.count(
                Appointment.id
            ).label("count"),
        )
        .where(
            Appointment.clinic_id
            == clinic.id,

            Appointment.created_at
            >= start_date,
        )
        .group_by("month")
        .order_by("month")
    )

    rows = result.all()

    return [
        {
            "month": row.month,
            "count": row.count,
        }
        for row in rows
    ]




async def get_growth_dashboard(
    *,
    db: AsyncSession,
):
    return {
        "monthly_patient_growth":
            await get_monthly_patient_growth(
                db=db
            ),

        "monthly_appointment_growth":
            await get_monthly_appointment_growth(
                db=db
            ),

        "monthly_revenue_growth":
            await get_monthly_revenue(
                db=db
            ),
    }