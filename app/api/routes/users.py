from fastapi import APIRouter, Depends
from app.security.jwt import get_current_user
from app.models.user import UserRole
from app.security.rbac import require_roles

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return{
        "message":"Authentication",
        "user":current_user
    }


@router.get("/admin")
def admin_dashboard(
    current_user = Depends(require_roles(UserRole.ADMIN))
):
    return {"message" : "Admin access granted"}



@router.post("/appoinments")
def create_appoinment(
    cuurent_user = Depends(require_roles(UserRole.RECEPTIONIST))
):
    return {"message" : "Appoinment created"}

