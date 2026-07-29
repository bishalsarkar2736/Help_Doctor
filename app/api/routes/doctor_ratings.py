from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.user import User, UserRole
from app.schemas.doctor_rating import (
    DoctorRatingCreate,
    DoctorRatingResponse,
    DoctorRatingSummary,
)
from app.security.rbac import require_roles
from app.services.doctor_rating_service import (
    is_editable,
    get_doctor_rating_summary,
    get_my_rating,
    submit_rating,
)
from app.try_except.exceptions import NotFoundError

router = APIRouter(tags=["Doctor ratings"])


def _to_response(rating) -> DoctorRatingResponse:
    """`editable` is derived from the clock, so it is not a column."""

    payload = DoctorRatingResponse.model_validate(rating)
    payload.editable = is_editable(rating)
    return payload


@router.post(
    "/appointments/{appointment_id}/rating",
    response_model=DoctorRatingResponse,
)
async def rate_appointment(
    appointment_id: int,
    payload: DoctorRatingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PATIENT)),
):
    """Rate the doctor for a completed visit. Re-posting edits the rating."""

    rating = await submit_rating(
        db=db,
        user=user,
        appointment_id=appointment_id,
        stars=payload.stars,
        comment=payload.comment,
    )
    await db.commit()
    await db.refresh(rating)

    return _to_response(rating)


@router.get(
    "/appointments/{appointment_id}/rating",
    response_model=DoctorRatingResponse,
)
async def read_my_rating(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PATIENT)),
):
    rating = await get_my_rating(
        db=db, user=user, appointment_id=appointment_id
    )
    if rating is None:
        raise NotFoundError("You have not rated this appointment")

    return _to_response(rating)


@router.get(
    "/doctors/{doctor_id}/rating-summary",
    response_model=DoctorRatingSummary,
)
async def doctor_rating_summary(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stars for a doctor.

    Open to any signed-in role including the doctor themselves — it carries no
    comments and no patient identity, so there is nothing here to de-anonymise.
    """

    return await get_doctor_rating_summary(db=db, doctor_id=doctor_id)
