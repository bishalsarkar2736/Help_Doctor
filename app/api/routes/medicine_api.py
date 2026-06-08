from fastapi import APIRouter,Query,Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.services.medicine_service import (
    get_medicine_by_name,
    search_medicines,
)

from app.core.metrics import (
    medicine_search_total,
    medicine_assistant_queries_total,
)

from app.schemas.medicine_assistant_schema import (
    MedicineAssistantRequest,
    MedicineAssistantResponse,
)

from app.services.medicine_assistant_service import (
    answer_medicine_question,
)


router = APIRouter(
    prefix="/medicines",
    tags=["Medicines"],
)


@router.get("/search")
async def search_medicine(
    name: str,
    db: AsyncSession = Depends(get_db),
):

    medicine_search_total.inc()

    return await get_medicine_by_name(
        db,
        name,
    )


@router.get("/autocomplete")
async def autocomplete_medicine(
    q: str = Query(..., min_length=2),
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    return await search_medicines(
        db,
        q,
        limit,
    )


@router.post(
    "/assistant",
    response_model=MedicineAssistantResponse,
)
async def medicine_assistant(
    payload: MedicineAssistantRequest,
    db: AsyncSession = Depends(get_db),
):

    medicine_assistant_queries_total.inc()

    answer = await answer_medicine_question(
        db=db,
        question=payload.question,
    )

    return MedicineAssistantResponse(
        answer=answer,
    )