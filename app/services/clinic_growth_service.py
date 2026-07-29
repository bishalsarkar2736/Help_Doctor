from datetime import date

from dateutil.relativedelta import relativedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment


from app.services.revenue_analytics_service import (
    get_monthly_revenue,
)




async def get_monthly_patient_growth(
    *,
    db: AsyncSession,
    clinic_id: int,
    months: int = 12,
):
    start_date = (
        date.today().replace(day=1)
        - relativedelta(months=months - 1)
    )

    # First appointment for each patient in this clinic
    first_visit_subquery = (
        select(
            Appointment.patient_id.label("patient_id"),
            func.min(Appointment.created_at).label("first_visit"),
        )
        .where(
            Appointment.clinic_id == clinic_id,
        )
        .group_by(Appointment.patient_id)
        .subquery()
    )

    result = await db.execute(
        select(
            func.to_char(
                first_visit_subquery.c.first_visit,
                "YYYY-MM",
            ).label("month"),
            func.count().label("count"),
        )
        .where(
            first_visit_subquery.c.first_visit >= start_date,
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
    clinic_id: int,
    months: int = 12,
):

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
            == clinic_id,

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
    clinic_id: int,
):
    return {
        "monthly_patient_growth":
            await get_monthly_patient_growth(
                db=db,
                clinic_id=clinic_id,
            ),

        "monthly_appointment_growth":
            await get_monthly_appointment_growth(
                db=db,
                clinic_id=clinic_id,
            ),

        "monthly_revenue_growth":
            await get_monthly_revenue(
                db=db,
                clinic_id=clinic_id,
            ),
    }