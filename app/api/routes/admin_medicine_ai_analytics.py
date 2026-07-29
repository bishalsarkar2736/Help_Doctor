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
    UserRole,User
)

from app.security.rbac import (
    require_roles,
)
from app.services.tenant_resolver import resolve_clinic_id
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
    clinic_id: int,
    db: AsyncSession = Depends(
        get_db
    ),
    admin: User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return {
        "total_ai_requests":
        await get_total_ai_requests(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "total_ai_failures":
        await get_total_ai_failures(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "average_latency_ms":
        await get_average_latency(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "estimated_cost":
        await get_estimated_cost(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "prompt_versions":
        await get_prompt_versions(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "top_questions":
        await get_top_ai_questions(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "tokens_by_medicine":
        await get_tokens_by_medicine(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "common_errors":
        await get_common_ai_errors(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "feedback_summary":
        await get_feedback_summary(
            db=db,
            clinic_id=resolved_clinic_id,
        ),

        "most_disliked_questions":
        await get_most_disliked_questions(
            db=db,
            clinic_id=resolved_clinic_id,
        ),
    }