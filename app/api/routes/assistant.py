"""The scheduling assistant endpoint.

Public and read-only. Everything it can say — which doctors practise here, when
they are free, the address, the opening hours — a clinic already publishes, and
nothing patient-specific passes through it. Requiring a login would block the
visitors it exists for.

Rate limiting lives inside the assistant rather than on this route, because the
limit applies to model calls and not to questions. A clinic that has exhausted
its AI budget must still be able to answer "when do you close?" from the
database, all day, for nothing.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.service import answer
from app.db.postgres import get_db
from app.models.clinic import Clinic
from app.services.clinic_context import require_clinic

router = APIRouter(prefix="/assistant", tags=["Assistant"])


class AssistantQuestion(BaseModel):
    # Bounded because it reaches a model that is billed by the token, and no
    # scheduling question needs more than a sentence or two.
    question: str = Field(min_length=1, max_length=500)


class AssistantAnswer(BaseModel):
    message: str
    intent: str
    result: dict
    formatted_by: str
    llm_unavailable_reason: str | None = None


def _client_ip(request: Request) -> str:
    """The caller, for per-IP limiting.

    X-Forwarded-For first, since nginx sits in front and request.client is the
    proxy otherwise — every visitor would share one bucket and the first twenty
    questions a minute would exhaust it for everyone.
    """
    forwarded = request.headers.get("x-forwarded-for", "")

    if forwarded:
        # Left-most entry is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


@router.post("/ask", response_model=AssistantAnswer)
async def ask(
    request: Request,
    payload: AssistantQuestion,
    db: AsyncSession = Depends(get_db),
    clinic: Clinic = Depends(require_clinic),
):
    """Answer one question about this clinic.

    The clinic comes from require_clinic, so every query underneath is scoped
    before this handler runs and the assistant has no way to reach another
    tenant's data.
    """
    return await answer(
        db,
        clinic,
        payload.question,
        client_ip=_client_ip(request),
    )
