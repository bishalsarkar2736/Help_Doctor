from fastapi import APIRouter, Depends

from app.models.user import UserRole,User
from app.security.rbac import require_roles
from app.services.presence_service import (
    is_user_online,
)

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
async def get_me(
    user: User = Depends(require_roles(
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
    }


@router.get("/admin")
def admin_dashboard(
    current_user = Depends(require_roles(UserRole.ADMIN))
):
    return {"message" : "Admin access granted"}



@router.post("/appointments")
def create_appoinment(
    cuurent_user = Depends(require_roles(UserRole.RECEPTIONIST))
):
    return {"message" : "Appoinment created"}



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