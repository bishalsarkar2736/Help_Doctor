from fastapi import Depends,HTTPException, status
from app.security.jwt import get_current_user
from app.models.user import UserRole


def require_roles(*allowed_roles : UserRole):
    """
    RBAC dependency
    Usage:
        Depends(require_roles(UserRole.ADMIN))
    """

    def role_checker(current_user=Depends(get_current_user)):
        user_role = current_user.get("role")

        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied"
            )
        
        return current_user
    
    return role_checker