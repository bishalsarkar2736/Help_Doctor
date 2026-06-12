from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import Payment


async def get_total_revenue(
    db: AsyncSession,
) -> float:

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            )
        ).where(
            Payment.status == "SUCCESS"
        )
    )

    return float(
        result.scalar_one()
    )


async def get_revenue_today(
    db: AsyncSession,
) -> float:

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            )
        )
        .where(
            Payment.status == "SUCCESS",
            func.date(
                Payment.created_at
            )
            == today,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_revenue_this_month(
    db: AsyncSession,
) -> float:

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            )
        )
        .where(
            Payment.status == "SUCCESS",
            func.extract(
                "month",
                Payment.created_at,
            )
            == today.month,
            func.extract(
                "year",
                Payment.created_at,
            )
            == today.year,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_monthly_revenue(
    db: AsyncSession,
    months: int = 12,
):
    start_date = (
        date.today().replace(day=1)
        - relativedelta(months=months - 1)
    )

    result = await db.execute(
        select(
            func.to_char(
                Payment.created_at,
                "YYYY-MM",
            ).label("month"),

            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            ).label("amount"),
        )
        .where(
            Payment.status == "SUCCESS",
            Payment.created_at >= start_date,
        )
        .group_by("month")
        .order_by("month")
    )

    rows = result.all()

    return [
        {
            "month": row.month,
            "amount": float(row.amount),
        }
        for row in rows
    ]


async def get_total_successful_payments(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Payment.id
            )
        ).where(
            Payment.status == "SUCCESS"
        )
    )

    return result.scalar_one()


async def get_revenue_analytics(
    db: AsyncSession,
):

    return {
        "total_revenue":
            await get_total_revenue(db),

        "revenue_this_month":
            await get_revenue_this_month(db),

        "revenue_today":
            await get_revenue_today(db),

        "total_payments":
            await get_total_successful_payments(db),

        "monthly_revenue":
            await get_monthly_revenue(db),
    }