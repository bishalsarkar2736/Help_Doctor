from sqlalchemy.ext.asyncio import AsyncSession

from app.services.clinic_analytics_service import (
    get_clinic_analytics,
)

from app.services.appointment_analytics_service import (
    get_appointment_analytics,
)

from app.services.revenue_analytics_service import (
    get_revenue_analytics,
    get_monthly_revenue,
)

from app.services.medicine_ai_analytics_service import (
    get_total_ai_requests,
    get_total_ai_failures,
    get_average_latency,
    get_estimated_cost,
    get_feedback_summary,
    get_most_disliked_questions,
)


async def get_dashboard_data(
    db: AsyncSession,
    clinic_id: int,
):

    clinic = await get_clinic_analytics(
        db=db,
        clinic_id=clinic_id,
    )

    appointments = await get_appointment_analytics(
        db=db,
        clinic_id=clinic_id,
    )

    revenue = await get_revenue_analytics(
        db=db,
        clinic_id=clinic_id,
    )

    revenue_trend = await get_monthly_revenue(
        db=db,
        clinic_id=clinic_id,
        months=12,
    )

    total_requests = await get_total_ai_requests(
        db,
        clinic_id,
    )

    total_failures = await get_total_ai_failures(
        db,
        clinic_id,
    )

    feedback_summary = await get_feedback_summary(
        db,
        clinic_id,
    )

    helpful = feedback_summary["helpful"]

    not_helpful = feedback_summary[
        "not_helpful"
    ]

    total_feedback = (
        helpful + not_helpful
    )

    helpful_percentage = (
        round(
            helpful * 100 / total_feedback,
            2,
        )
        if total_feedback
        else 0.0
    )

    ai = {
        "total_requests": total_requests,

        "total_failures": total_failures,

        "failure_rate_percent": round(
            (
                total_failures
                / total_requests
                * 100
            )
            if total_requests
            else 0,
            2,
        ),

        "average_latency_ms":
            await get_average_latency(
                db,
                clinic_id,
            ),

        "estimated_cost":
            await get_estimated_cost(
                db,
                clinic_id,
            ),
    }

    ai_quality = {

        "feedback_summary":
            feedback_summary,

        "helpful_percentage":
            helpful_percentage,

        "most_disliked_questions":
            await get_most_disliked_questions(
                db,
                clinic_id,
            ),
    }

    return {
        "clinic": clinic,

        "appointments": appointments,

        "revenue": revenue,

        "revenue_trend": revenue_trend,

        "ai": ai,

        "ai_quality": ai_quality,
    }