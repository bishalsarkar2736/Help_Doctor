from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import UTC
from app.legal.documents import LegalDocumentType
from app.services.consent_service import record_consents, validate_versions
from app.models.user import User, UserRole, AuthProvider
from app.models.invitation import Invitation, InvitationStatus
from app.schemas.invitation import (
    InvitationCreate,
    InvitationAccept,
    InvitationPreview,
)
from app.security.tokens import generate_secure_token, hash_token
from app.security.jwt import hash_password
from app.services.clinic_service import get_clinic_by_id
from app.services.email import send_invitation_email
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)


INVITATION_TTL_DAYS = 7

# Who may invite which roles.
_INVITE_MATRIX: dict[UserRole, set[UserRole]] = {
    UserRole.SUPER_ADMIN: {UserRole.ADMIN},
    UserRole.ADMIN: {UserRole.RECEPTIONIST, UserRole.DOCTOR},
}


async def _resolve_invite_clinic(
    inviter: User,
    role: UserRole,
    requested_clinic_id: int,
) -> int:
    """Validate the inviter/role/clinic combination and return the clinic id."""

    allowed = _INVITE_MATRIX.get(inviter.role)

    if not allowed or role not in allowed:
        raise ForbiddenError(
            "You are not allowed to invite a user with this role"
        )

    # Never invite privileged/self-service roles.
    if role in {UserRole.SUPER_ADMIN, UserRole.PATIENT}:
        raise ForbiddenError("This role cannot be invited")

    # Clinic admins can only invite into their own clinic.
    if inviter.role == UserRole.ADMIN:
        if not inviter.clinic_id:
            raise ForbiddenError("Admin is not assigned to a clinic")
        if requested_clinic_id != inviter.clinic_id:
            raise ForbiddenError("Cannot invite users to another clinic")
        return inviter.clinic_id

    # Super admin invites clinic admins into any (existing) clinic.
    return requested_clinic_id


async def create_invitation(
    db: AsyncSession,
    inviter: User,
    payload: InvitationCreate,
) -> Invitation:
    clinic_id = await _resolve_invite_clinic(
        inviter=inviter,
        role=payload.role,
        requested_clinic_id=payload.clinic_id,
    )

    clinic = await get_clinic_by_id(db=db, clinic_id=clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")

    email = str(payload.email).lower()

    # Block inviting an email that already has an account.
    existing_user = await db.scalar(
        select(User).where(User.email == email)
    )
    if existing_user is not None:
        raise BadRequestError("A user with this email already exists")

    # Supersede any earlier pending invite for the same email+clinic.
    old_pending = await db.scalars(
        select(Invitation).where(
            Invitation.email == email,
            Invitation.clinic_id == clinic_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    for old in old_pending:
        old.status = InvitationStatus.REVOKED

    raw_token = generate_secure_token()

    invitation = Invitation(
        email=email,
        role=payload.role,
        clinic_id=clinic_id,
        token_hash=hash_token(raw_token),
        status=InvitationStatus.PENDING,
        invited_by_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
    )

    db.add(invitation)
    await db.flush()
    await db.refresh(invitation)

    await send_invitation_email(
        email=email,
        token=raw_token,
        clinic_name=clinic.name,
        role=payload.role.value,
    )

    return invitation


async def _load_valid_pending(
    db: AsyncSession,
    token: str,
) -> Invitation:
    invitation = await db.scalar(
        select(Invitation).where(
            Invitation.token_hash == hash_token(token)
        )
    )

    if invitation is None:
        raise BadRequestError("Invalid invitation token")

    if invitation.status == InvitationStatus.ACCEPTED:
        raise BadRequestError("Invitation has already been accepted")

    if invitation.status == InvitationStatus.REVOKED:
        raise BadRequestError("Invitation has been revoked")

    if invitation.expires_at < datetime.now(UTC):
        raise BadRequestError("Invitation has expired")

    return invitation


async def get_invitation_preview(
    db: AsyncSession,
    token: str,
) -> InvitationPreview:
    invitation = await _load_valid_pending(db, token)

    clinic = await get_clinic_by_id(db=db, clinic_id=invitation.clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")

    return InvitationPreview(
        email=invitation.email,
        role=invitation.role,
        clinic_id=invitation.clinic_id,
        clinic_name=clinic.name,
        expires_at=invitation.expires_at,
    )


async def accept_invitation(
    db: AsyncSession,
    payload: InvitationAccept,
    request = None,
) -> User:
    # Validated before the invitation is consumed, so a rejected consent does
    # not burn a single-use token.
    accepted = {
        LegalDocumentType.TERMS: payload.accepted_terms_version,
        LegalDocumentType.PRIVACY: payload.accepted_privacy_version,
    }
    validate_versions(accepted)

    invitation = await _load_valid_pending(db, payload.token)

    existing_user = await db.scalar(
        select(User).where(User.email == invitation.email)
    )
    if existing_user is not None:
        raise BadRequestError("An account with this email already exists")

    user = User(
        email=invitation.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=invitation.role,
        clinic_id=invitation.clinic_id,
        is_active=True,
        # Accepting via the emailed token proves ownership of the address.
        is_email_verified=True,
        auth_provider=AuthProvider.LOCAL,
    )

    db.add(user)
    await db.flush()

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.now(UTC)
    invitation.accepted_user_id = user.id

    await db.flush()
    await db.refresh(user)

    # Same transaction as the account, for the same reason as registration.
    await record_consents(db=db, user=user, accepted=accepted, request=request)

    return user


async def list_invitations(
    db: AsyncSession,
    requester: User,
    clinic_id: int | None = None,
    status: InvitationStatus | None = None,
) -> list[Invitation]:
    query = select(Invitation).order_by(Invitation.created_at.desc())

    if requester.role == UserRole.ADMIN:
        # Clinic admins only ever see their own clinic's invitations.
        query = query.where(Invitation.clinic_id == requester.clinic_id)
    elif clinic_id is not None:
        query = query.where(Invitation.clinic_id == clinic_id)

    if status is not None:
        query = query.where(Invitation.status == status)

    result = await db.scalars(query)
    return list(result)


async def revoke_invitation(
    db: AsyncSession,
    requester: User,
    invitation_id: int,
) -> Invitation:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise NotFoundError("Invitation not found")

    if (
        requester.role == UserRole.ADMIN
        and invitation.clinic_id != requester.clinic_id
    ):
        raise ForbiddenError("Cannot manage another clinic's invitation")

    if invitation.status != InvitationStatus.PENDING:
        raise BadRequestError("Only pending invitations can be revoked")

    invitation.status = InvitationStatus.REVOKED
    await db.flush()
    await db.refresh(invitation)

    return invitation
