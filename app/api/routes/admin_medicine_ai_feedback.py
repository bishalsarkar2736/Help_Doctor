from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)
from app.models.medicine_ai_log import MedicineAILog
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.schemas.medicine_ai_feedback_schema import (
    MedicineAIFeedbackCreate,
)
from app.security.rbac import require_roles
from app.services.medicine_ai_feedback_service import (
    create_feedback,
)

from app.models.user import User,UserRole
from app.services.tenant_resolver import resolve_clinic_id

router = APIRouter(
    prefix="/admin/medicine-ai",
    tags=["Medicine AI Feedback"],
)


@router.post(
    "/logs/{log_id}/feedback",
)
async def submit_feedback(
    log_id: int,
    clinic_id: int,
    payload: MedicineAIFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(
        require_roles(UserRole.ADMIN)
    ),
):

    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    result = await db.execute(
        select(MedicineAILog).where(
            MedicineAILog.id == log_id,
            MedicineAILog.clinic_id == resolved_clinic_id,
        )
    )

    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(
            status_code=404,
            detail="AI log not found.",
        )

    feedback = await create_feedback(
        db=db,
        ai_log_id=log_id,
        helpful=payload.helpful,
    )

    return {
        "id": feedback.id,
        "helpful": feedback.helpful,
    }