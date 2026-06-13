from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import UserRole,User

from app.security.rbac import (
    require_roles,
)

from app.services.medicine_matcher_service import (
    match_medicine,
)

from app.services.medicine_ai_service import (
    MedicineAIService,
)

router = APIRouter(
    prefix="/admin/medicine-ai",
    tags=["Medicine AI"],
)


@router.post("/test")
async def test_medicine_ai(
    question: str,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    medicine = await match_medicine(
        db=db,
        question=question,
    )

    if not medicine:
        return {
            "message":
            "Medicine not found"
        }

    service = MedicineAIService()

    answer = await service.answer(
        db=db,
        medicine=medicine,
        question=question,
    )

    return {
        "medicine":
        medicine.name,

        "answer":
        answer,
    }