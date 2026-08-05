from fastapi import APIRouter, Depends, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.user import User, UserRole
from app.models.invitation import InvitationStatus
from app.security.rbac import require_roles
from app.schemas.invitation import (
    InvitationCreate,
    InvitationRead,
    InvitationPreview,
    InvitationAccept,
    InvitationAcceptResponse,
)
from app.services.invitation_service import (
    create_invitation,
    get_invitation_preview,
    accept_invitation,
    list_invitations,
    revoke_invitation,
)

router = APIRouter(prefix="/invitations", tags=["Invitations"])


# ---------------- CREATE (Super Admin / Clinic Admin) ----------------

@router.post(
    "",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation_endpoint(
    payload: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    inviter: User = Depends(
        require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)
    ),
):
    return await create_invitation(db=db, inviter=inviter, payload=payload)


# ---------------- LIST (Super Admin / Clinic Admin) ----------------

@router.get(
    "",
    response_model=list[InvitationRead],
)
async def list_invitations_endpoint(
    clinic_id: int | None = Query(default=None),
    status_filter: InvitationStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    requester: User = Depends(
        require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)
    ),
):
    return await list_invitations(
        db=db,
        requester=requester,
        clinic_id=clinic_id,
        status=status_filter,
    )


# ---------------- PREVIEW (public) ----------------

@router.get(
    "/preview",
    response_model=InvitationPreview,
)
async def preview_invitation_endpoint(
    token: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    return await get_invitation_preview(db=db, token=token)


# ---------------- ACCEPT (public) ----------------

@router.post(
    "/accept",
    response_model=InvitationAcceptResponse,
)
async def accept_invitation_endpoint(
    request: Request,
    payload: InvitationAccept,
    db: AsyncSession = Depends(get_db),
):
    user = await accept_invitation(db=db, payload=payload, request=request)

    return InvitationAcceptResponse(
        message="Invitation accepted. You can now sign in.",
        user_id=user.id,
        email=user.email,
        role=user.role,
    )


# ---------------- REVOKE (Super Admin / Clinic Admin) ----------------

@router.post(
    "/{invitation_id}/revoke",
    response_model=InvitationRead,
)
async def revoke_invitation_endpoint(
    invitation_id: int,
    db: AsyncSession = Depends(get_db),
    requester: User = Depends(
        require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)
    ),
):
    return await revoke_invitation(
        db=db,
        requester=requester,
        invitation_id=invitation_id,
    )
