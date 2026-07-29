from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.user import User, UserRole
from app.schemas.doctor_rating import AdminDoctorRatingItem
from app.security.rbac import require_roles
from app.services.doctor_rating_service import list_ratings_for_admin
from app.services.tenant_resolver import resolve_clinic_id

router = APIRouter(prefix="/admin/doctors", tags=["Admin: doctor ratings"])


@router.get("/{doctor_id}/ratings", response_model=list[AdminDoctorRatingItem])
async def admin_list_doctor_ratings(
    doctor_id: int,
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    """Ratings *with* the written comments — the only endpoint that exposes them.

    Scoped through resolve_clinic_id so one clinic's admin can never read
    feedback left at another clinic.
    """

    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await list_ratings_for_admin(
        db=db,
        clinic_id=resolved_clinic_id,
        doctor_id=doctor_id,
        limit=limit,
        offset=offset,
    )
