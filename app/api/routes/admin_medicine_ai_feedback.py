from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.schemas.medicine_ai_feedback_schema import (
    MedicineAIFeedbackCreate,
)

from app.services.medicine_ai_feedback_service import (
    create_feedback,
)

router = APIRouter(
    prefix="/admin/medicine-ai",
    tags=["Medicine AI Feedback"],
)


@router.post(
    "/logs/{log_id}/feedback"
)
async def submit_feedback(
    log_id: int,
    payload: MedicineAIFeedbackCreate,
    db: AsyncSession = Depends(get_db),
):

    feedback = await create_feedback(
        db=db,
        ai_log_id=log_id,
        helpful=payload.helpful,
    )

    return {
        "id": feedback.id,
        "helpful": feedback.helpful,
    }