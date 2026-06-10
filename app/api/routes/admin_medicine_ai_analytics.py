from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.db.postgres import (
    get_db,
)

from app.models.user import (
    UserRole,
)

from app.security.rbac import (
    require_roles,
)

from app.services.medicine_ai_analytics_service import (
    get_average_latency,
    get_estimated_cost,
    get_prompt_versions,
    get_top_ai_questions,
    get_tokens_by_medicine,
    get_total_ai_requests,
    get_common_ai_errors,
    get_total_ai_failures,
    get_feedback_summary,
    get_most_disliked_questions,
)

router = APIRouter(
    prefix="/admin/medicine-ai",
    tags=["Medicine AI Analytics"],
)


@router.get("/analytics")
async def medicine_ai_analytics(
    db: AsyncSession = Depends(
        get_db
    ),
    admin=Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return {
        "total_ai_requests":
        await get_total_ai_requests(
            db
        ),

        "total_ai_failures":
        await get_total_ai_failures(
            db
        ),

        "average_latency_ms":
        await get_average_latency(
            db
        ),

        "estimated_cost":
        await get_estimated_cost(
            db
        ),

        "prompt_versions":
        await get_prompt_versions(
            db
        ),

        "top_questions":
        await get_top_ai_questions(
            db
        ),

        "tokens_by_medicine":
        await get_tokens_by_medicine(
            db
        ),

        "common_errors":
        await get_common_ai_errors(
            db
        ),

        "feedback_summary":
        await get_feedback_summary(
            db
        ),

        "most_disliked_questions":
        await get_most_disliked_questions(
            db
        ),
    }