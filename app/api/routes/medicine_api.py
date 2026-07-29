from fastapi import APIRouter, Query, Depends, Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.user import User
from app.services.tenant_resolver import resolve_clinic_id

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
    dependencies=[Depends(get_current_user)],
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
@limiter.limit("10/minute")
async def medicine_assistant(
    request: Request,
    payload: MedicineAssistantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Resolve the tenant the query is logged under (required, NOT NULL FK).
    clinic_id = await resolve_clinic_id(
        db=db,
        user=current_user,
        clinic_id=payload.clinic_id,
    )

    # NOTE: the request counter is incremented inside
    # answer_medicine_question — do not double-count here.

    answer = await answer_medicine_question(
        db=db,
        clinic_id=clinic_id,
        question=payload.question,
    )

    return MedicineAssistantResponse(
        answer=answer,
    )