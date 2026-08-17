from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.doctor import Doctor
from app.models.user import UserRole,User
from app.security.rbac import require_roles
from app.security.mfa_policy import mfa_enrollment_pending, mfa_required_for
from app.services.presence_service import (
    is_user_online,
)
from app.try_except.exceptions import ForbiddenError

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
async def get_me(
    user: User = Depends(require_roles(
        UserRole.SUPER_ADMIN,
        UserRole.ADMIN,
        UserRole.DOCTOR,
        UserRole.PATIENT,
        UserRole.RECEPTIONIST,
    ))
):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "clinic_id": user.clinic_id,
        "mfa_enabled": user.mfa_enabled,
        # Whether this user's ROLE mandates a second factor, and whether they
        # still owe enrolment. The client uses these to route to the enrolment
        # screen rather than letting the user discover the requirement as a
        # 403 partway through a privileged action.
        "mfa_required": mfa_required_for(user.role),
        "mfa_enrollment_required": mfa_enrollment_pending(user),
    }


@router.get("/admin")
def admin_dashboard(
    current_user = Depends(require_roles(UserRole.ADMIN))
):
    return {"message" : "Admin access granted"}



async def _presence_subject_clinic_id(
    db: AsyncSession, user_id: int
) -> int | None:
    """The clinic the observed user belongs to, or None.

    A doctor's clinic lives on their Doctor row rather than User.clinic_id —
    the asymmetry _searcher_clinic_id and _caller_clinic_id already document —
    so reading User.clinic_id alone would deny a receptionist their own
    clinic's doctors.

    None for a user who does not exist, a patient (patients are global and
    belong to no clinic), and a doctor with no clinic. All three are refused
    identically by the caller, which is what keeps this from answering whether
    an id exists.
    """
    target = await db.scalar(select(User).where(User.id == user_id))

    if target is None:
        return None

    if target.role == UserRole.DOCTOR:
        return await db.scalar(
            select(Doctor.clinic_id).where(Doctor.user_id == target.id)
        )

    return target.clinic_id


@router.get("/{user_id}/presence")
async def get_presence(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
            UserRole.RECEPTIONIST,
        )
    ),
):
    """Whether a user is currently connected.

    The role gate answered "is the caller a valid user" and the client-supplied
    id was passed straight to the presence lookup, so any principal of any role
    could poll any user across every clinic — and user ids are sequential.

    Clinic staff may observe their own clinic's people, which is the front-desk
    case. Doctors and patients get themselves only: nothing in the frontend
    calls this endpoint, so granting either a wider view would be inventing a
    feature rather than preserving one.

    Every refusal is the same error, so an unknown id is indistinguishable from
    a real user in another clinic and probing cannot enumerate the user table.
    """
    if user_id != current_user.id:

        if current_user.role not in (UserRole.ADMIN, UserRole.RECEPTIONIST):
            raise ForbiddenError("Not allowed")

        # Fails closed on staff with no clinic — an account resolve_clinic_id
        # and _searcher_clinic_id both already refuse.
        if not current_user.clinic_id:
            raise ForbiddenError("Not allowed")

        subject_clinic_id = await _presence_subject_clinic_id(db, user_id)

        if (
            subject_clinic_id is None
            or subject_clinic_id != current_user.clinic_id
        ):
            raise ForbiddenError("Not allowed")

    online = await is_user_online(user_id)

    return {
        "user_id": user_id,
        "online": online,
    }