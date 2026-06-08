# from fastapi import Depends, HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.db.postgres import get_db
# from app.security.jwt import get_current_user
# from app.models.user import User, UserRole


# def require_roles(*allowed_roles: UserRole):
#     """
#     RBAC dependency

#     Usage:
#         Depends(require_roles(UserRole.ADMIN))
#         Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))
#     """

#     async def role_checker(
#         db: AsyncSession = Depends(get_db),
#         current_user_payload: dict = Depends(get_current_user),
#     ) -> User:

#         # 🔹 Extract user ID from JWT
#         user_id = current_user_payload.get("sub")

#         if not user_id:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid token payload",
#             )

#         # 🔹 Load user from DB
#         user = await db.get(User, int(user_id))

#         if not user:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail="User not found",
#             )

#         # 🔹 Check active status
#         if not user.is_active:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Inactive user",
#             )

#         # 🔹 Check role
#         if user.role not in allowed_roles:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Permission denied",
#             )

#         return user

#     return role_checker


from fastapi import Depends, HTTPException, status

from app.security.jwt import get_current_user
from app.models.user import User, UserRole


def require_roles(*allowed_roles: UserRole):
    """
    RBAC dependency

    Usage:
        Depends(require_roles(UserRole.ADMIN))
        Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))
    """

    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:

        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

        return current_user

    return role_checker