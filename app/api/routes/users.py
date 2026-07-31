from fastapi import APIRouter, Depends

from app.models.user import UserRole,User
from app.security.rbac import require_roles
from app.security.mfa_policy import mfa_enrollment_pending, mfa_required_for
from app.services.presence_service import (
    is_user_online,
)

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



@router.get("/{user_id}/presence")
async def get_presence(
    user_id: int,
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
            UserRole.RECEPTIONIST,
        )
    ),
):
    online = await is_user_online(user_id)

    return {
        "user_id": user_id,
        "online": online,
    }