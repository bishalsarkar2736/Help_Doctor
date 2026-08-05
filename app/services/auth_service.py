import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User,AuthProvider,UserRole
from app.models.doctor import Doctor
from app.models.clinic import Clinic, ClinicStatus
from app.schemas.user import UserCreate, SELF_REGISTERABLE_ROLES
from app.security.jwt import hash_password,verify_password
from app.security.mfa import verify_code
from app.security.mfa_policy import mfa_enrollment_pending
from app.legal.documents import LegalDocumentType
from app.services.consent_service import record_consents, validate_versions
from app.security.google_oauth import verify_google_token
from app.config import get_settings

from datetime import datetime, timedelta
from app.core.time import UTC
from app.core.metrics import login_attempts_total
from app.models.refresh_token import RefreshToken
from app.security.jwt import create_access_token
from app.core.security import create_refresh_token
from app.try_except.exceptions import BadRequestError,UnauthorizedError,ForbiddenError
from app.try_except.audit import log_audit_event
from app.models.email_verification_token import (
    EmailVerificationToken,
    TOKEN_TYPE_LINK,
    TOKEN_TYPE_OTP,
)
from app.models.password_reset_token import PasswordResetToken
from app.security.tokens import (
    generate_secure_token,
    generate_otp,
    hash_token,
    verify_token_hash,
)
from app.services.email import (
    send_password_reset_email,
    send_email_verification_email,
    send_email_verification_otp,
)


settings = get_settings()

logger = logging.getLogger(__name__)



async def _assert_clinic_active(
    db: AsyncSession,
    user: User,
) -> None:
    """Block token issuance if the user belongs to a suspended/deleted clinic.

    Patients, super admins and unassigned users are not clinic-bound and pass
    through. A doctor's clinic may live on the Doctor row (self-registered),
    so we resolve that too.
    """
    clinic_id = user.clinic_id

    if clinic_id is None and user.role == UserRole.DOCTOR:
        doctor = await db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )
        clinic_id = doctor.clinic_id if doctor else None

    if clinic_id is None:
        return

    clinic = await db.get(Clinic, clinic_id)

    if clinic is not None and clinic.status != ClinicStatus.ACTIVE:
        raise ForbiddenError(
            "This clinic is currently unavailable. Please contact support."
        )


async def _issue_tokens(
    db: AsyncSession,
    user: User,
) -> dict:
    """
    Create JWT access token and opaque refresh token.
    """

    await _assert_clinic_active(db, user)


    access_token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role.value,
        }
    )

    refresh_token = create_refresh_token()

    refresh = RefreshToken(
        token=refresh_token,
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(refresh)
    await db.flush()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        # This user's role mandates a second factor and they have not set one
        # up. Login still succeeds on purpose — enrolling needs an
        # authenticated session, so refusing here would lock the account out
        # with no route back (see app/security/mfa_policy.py). The client sends
        # them to enrolment; privileged endpoints refuse until it is done.
        "mfa_enrollment_required": mfa_enrollment_pending(user),
    }




# Register user
async def register_user(
        db : AsyncSession,
        user_in : UserCreate,
        request = None,
) -> User:
    # Refuse before creating anything. An account that exists without a valid
    # consent record is the state this whole feature exists to prevent, and it
    # is far easier to reject the request than to reconcile it afterwards.
    accepted = {
        LegalDocumentType.TERMS: user_in.accepted_terms_version,
        LegalDocumentType.PRIVACY: user_in.accepted_privacy_version,
    }
    validate_versions(accepted)
    result = await db.execute(
        select(User).where(User.email == user_in.email)
    )

    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise BadRequestError("Email already registered")

    # Defence in depth: the schema already rejects privileged roles, but never
    # let a self-service signup mint staff/platform accounts even if this
    # service is called from somewhere else.
    if user_in.role not in SELF_REGISTERABLE_ROLES:
        raise ForbiddenError(
            "This account type cannot be created by signing up."
        )

    user = User(
        email = user_in.email,
        full_name = user_in.full_name,
        hashed_password = hash_password(user_in.password),
        role = user_in.role,
        is_active = True,
    )

    db.add(user)
    await db.flush()
    #await db.commit()
    await db.refresh(user)

    # Same transaction as the account: an account without its consent record,
    # or a consent record for an account that failed to create, are both worse
    # than failing the whole request. Deliberately NOT wrapped in try/except —
    # unlike the email below, this one is evidence and must not be best-effort.
    await record_consents(db=db, user=user, accepted=accepted, request=request)

    # Kick off email verification with a one-time code. Never fail signup if
    # email delivery fails — the user can request a new code from the OTP page.
    try:
        await _issue_verification_otp(db, user)
    except Exception:
        logger.exception("Failed to send verification OTP on registration")

    return user

# async def get_or_create_google_user(
#         db : AsyncSession,
#         token : str
# ) -> User:
#     data = verify_google_token(token)

#     stmt = select(User).where(User.email==data["email"])
#     result = await db.execute(stmt)
#     user = result.scalar_one_or_none()

#     if user:
#         return user
    
#     user = User(
#         email = data["email"],
#         full_name = data["full_name"],
#         google_id = data["google_id"],
#         auth_provider = AuthProvider.GOOGLE,
#         role = UserRole.PATIENT,
#         is_active = True,
#     )

#     db.add(user)
#     await db.flush()
#     #await db.commit()
#     await db.refresh(user)

#     return user


async def authenticate_google_user(
    db: AsyncSession,
    token: str,
) -> dict:

    data = verify_google_token(token)

    result = await db.execute(
        select(User).where(User.email == data["email"])
    )

    user = result.scalar_one_or_none()

    if user:

        if user.deleted_at is not None:
            raise ForbiddenError("This account has been deleted")

        if not user.is_active:
            raise ForbiddenError("Inactive user")

        # Link existing account
        if user.google_id is None:
            user.google_id = data["google_id"]

        user.auth_provider = AuthProvider.GOOGLE
        # Google has already verified the address.
        user.is_email_verified = True

        await db.flush()

        return await _issue_tokens(db, user)

    # Create new Google user
    user = User(
        email=data["email"],
        full_name=data["full_name"],
        hashed_password=None,
        google_id=data["google_id"],
        auth_provider=AuthProvider.GOOGLE,
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )

    db.add(user)

    await db.flush()
    await db.refresh(user)

    return await _issue_tokens(db, user)



# Authentication User

async def authentication_user(
    db: AsyncSession,
    email: str,
    password: str,
    mfa_code: str | None = None,
):
    try:
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise UnauthorizedError("Invalid email or password")

        if user.hashed_password is None:
            raise UnauthorizedError(
                "This account uses Google Sign-In."
            )

        if not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")

        # Checked before is_active so a deleted account never reads as merely
        # suspended — deletion is permanent and cannot be toggled back on.
        if user.deleted_at is not None:
            raise ForbiddenError("This account has been deleted")

        if not user.is_active:
            raise ForbiddenError("Inactive user")

        if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
            raise ForbiddenError(
                "Please verify your email before logging in."
            )

        # Second factor. "MFA_REQUIRED" is a machine-readable signal the client
        # uses to prompt for a code, then resubmit login with it.
        if user.mfa_enabled:
            if not mfa_code:
                raise UnauthorizedError("MFA_REQUIRED")
            if not verify_code(user.mfa_secret, mfa_code):
                raise UnauthorizedError("Invalid MFA code")
    except (UnauthorizedError, ForbiddenError):
        login_attempts_total.labels(result="failure").inc()
        raise

    tokens = await _issue_tokens(db, user)
    login_attempts_total.labels(result="success").inc()
    return tokens


async def refresh_tokens(
    db: AsyncSession,
    refresh_token: str,
):
    # 1️⃣ Validate refresh token from DB
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise UnauthorizedError("Invalid or expired refresh token")

    # 2️⃣ Fetch user
    user = await db.get(User, db_token.user_id)
    if not user:
        raise UnauthorizedError("User not found")

    # 2.5️⃣ Block refresh for suspended/deleted clinics.
    await _assert_clinic_active(db, user)

    # 3️⃣ Revoke old refresh token (rotation)
    db_token.revoked = True

    # 4️⃣ Create new refresh token (opaque)
    new_refresh_token = create_refresh_token()

    new_db_token = RefreshToken(
        token=new_refresh_token,
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(new_db_token)

    # 5️⃣ Create new access token (JWT)
    access_token = create_access_token(
        {"sub": str(user.id), "role": user.role.value}
    )

    await db.flush()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }



async def logout_user(
    db: AsyncSession,
    refresh_token: str,
):
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.revoked.is_(False),
        )
    )

    db_token = result.scalar_one_or_none()

    if not db_token:
        # already revoked or invalid → still treat as success
        return {"message": "Logged out"}

    db_token.revoked = True
    db_token.revoked_at = datetime.now(UTC)

    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=db_token.user_id,
        action="logout",
        resource="user_account",
        status="success",
    )

    #await db.commit()
    await db.flush()

    return {"message": "Logged out successfully"}



async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
):
    """
    Change the password for an authenticated user.

    Security:
    - Verify current password
    - Prevent reusing the same password
    - Hash new password
    - Revoke all refresh tokens
    - Audit log
    """

    if user.hashed_password is None:
        raise BadRequestError(
            "This account uses Google Sign-In and does not have a password."
        )

    if not verify_password(
        current_password,
        user.hashed_password,
    ):
        raise UnauthorizedError(
            "Current password is incorrect"
        )


    if verify_password(new_password, user.hashed_password):
        raise BadRequestError(
            "New password must be different from the current password"
        )

    # Update password
    user.hashed_password = hash_password(new_password)

    # Revoke all refresh tokens
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked.is_(False),
        )
    )

    refresh_tokens = result.scalars().all()


    for token in refresh_tokens:
        token.revoked = True

    # Audit log
    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=user.id,
        action="change_password",
        resource="user_account",
        status="success",
    )

    await db.flush()

    return {
        "message": "Password changed successfully. Please log in again."
    }


async def forgot_password(
    db: AsyncSession,
    email: str,
):
    """
    Send a password reset email if the account exists.

    Always returns the same response to prevent
    email enumeration attacks.
    """

    result = await db.execute(
        select(User).where(User.email == email)
    )

    user = result.scalar_one_or_none()

    if user is not None:

        token = generate_secure_token()

        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC)
            + timedelta(hours=1),
        )

        db.add(reset_token)

        await db.flush()

        await send_password_reset_email(
            email=user.email,
            token=token,
        )

    return {
        "message": (
            "If an account exists, "
            "a password reset email has been sent."
        )
    }



async def reset_password(
    db: AsyncSession,
    token: str,
    new_password: str,
):
    """
    Reset a user's password using a one-time reset token.

    Security:
    - Token must exist
    - Token must not be expired
    - Token must not be used
    - Password is re-hashed
    - Reset token becomes one-time use
    - All refresh tokens are revoked
    - Audit log is written
    """

    token_hash = hash_token(token)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
        )
    )

    reset = result.scalar_one_or_none()

    if reset is None:
        raise BadRequestError("Invalid reset token")

    if reset.used:
        raise BadRequestError("Reset token has already been used")

    if reset.expires_at < datetime.now(UTC):
        raise BadRequestError("Reset token has expired")

    user = await db.get(User, reset.user_id)

    if user is None:
        raise BadRequestError("User not found")
    

    if (
        user.hashed_password is not None
        and verify_password(
            new_password,
            user.hashed_password,
        )
    ):
        raise BadRequestError(
            "New password must be different from the current password."
        )

    #
    # Update password
    #

    user.hashed_password = hash_password(new_password)

    #
    # Mark reset token used
    #

    reset.used = True

    #
    # Revoke every refresh token
    #

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked.is_(False),
        )
    )

    refresh_tokens = result.scalars().all()

    for refresh in refresh_tokens:
        refresh.revoked = True

    #
    # Audit log
    #

    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=user.id,
        action="reset_password",
        resource="user_account",
        status="success",
    )

    await db.flush()

    return {
        "message": "Password has been reset successfully."
    }


# --- OTP email verification -------------------------------------------------
# A 6-digit code has only 1,000,000 possibilities, so unlike the long link
# token it MUST be (a) scoped to one user and (b) attempt-limited.
OTP_EXPIRY_MINUTES = 10
MAX_OTP_ATTEMPTS = 5


async def _issue_verification_otp(
    db: AsyncSession,
    user: User,
) -> None:
    """Invalidate any outstanding codes, mint a new OTP, and email it."""

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used.is_(False),
        )
    )
    for old in result.scalars():
        await db.delete(old)

    code = generate_otp()

    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_type=TOKEN_TYPE_OTP,
            # Argon2, not SHA-256: a 6-digit code has only ~20 bits of
            # entropy, so a bare digest of it is trivially reversible by
            # anyone who can read this table. Lookup is by user_id, so a
            # non-deterministic hash costs us nothing here.
            token_hash=hash_password(code),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=OTP_EXPIRY_MINUTES),
        )
    )

    await db.flush()

    # Only the delivery is best-effort. A DB failure above MUST propagate:
    # swallowing it would leave the session in a failed transaction, so the
    # outer commit rolls back and registration silently loses the user while
    # still returning 201.
    try:
        await send_email_verification_otp(
            email=user.email,
            code=code,
            expires_minutes=OTP_EXPIRY_MINUTES,
        )
    except Exception:
        logger.exception(
            "Failed to deliver verification OTP",
            extra={"user_id": user.id},
        )


async def verify_email_otp(
    db: AsyncSession,
    email: str,
    code: str,
):
    """Verify a registration OTP.

    Scoped by email so a guessed code can only ever match the account it was
    issued for, and capped at MAX_OTP_ATTEMPTS to stop brute forcing.
    """

    generic_error = "Invalid or expired verification code."

    user = await db.scalar(
        select(User).where(User.email == email)
    )

    # Don't reveal whether the address exists.
    if user is None:
        raise BadRequestError(generic_error)

    if user.is_email_verified:
        raise BadRequestError("Email is already verified.")

    verification = await db.scalar(
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used.is_(False),
            EmailVerificationToken.token_type == TOKEN_TYPE_OTP,
        )
        .order_by(EmailVerificationToken.created_at.desc())
    )

    if verification is None:
        raise BadRequestError(generic_error)

    if verification.expires_at < datetime.now(UTC):
        raise BadRequestError("Verification code has expired.")

    if verification.attempts >= MAX_OTP_ATTEMPTS:
        raise BadRequestError(
            "Too many incorrect attempts. Please request a new code."
        )

    if not verify_password(code, verification.token_hash):
        verification.attempts += 1

        await log_audit_event(
            db=db,
            event_type="authentication",
            user_id=user.id,
            action="verify_email_otp",
            resource="user_account",
            status="failure",
        )

        # COMMIT before raising. The exception propagates to get_db, which
        # rolls the session back — a plain flush() here would be discarded and
        # the brute-force counter would never actually increment.
        await db.commit()

        raise BadRequestError(generic_error)

    user.is_email_verified = True
    verification.used = True

    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=user.id,
        action="verify_email_otp",
        resource="user_account",
        status="success",
    )

    await db.flush()

    return {"message": "Email verified successfully."}


async def _issue_verification_email(
    db: AsyncSession,
    user: User,
) -> None:
    """Invalidate old tokens, mint a new one, and email it. Shared by
    register (auto), the authenticated resend, and the public resend."""

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used.is_(False),
        )
    )

    for token in result.scalars():
        await db.delete(token)

    raw_token = generate_secure_token()

    verification = EmailVerificationToken(
        user_id=user.id,
        token_type=TOKEN_TYPE_LINK,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC)
        + timedelta(hours=24),
    )

    db.add(verification)

    await db.flush()

    await send_email_verification_email(
        email=user.email,
        token=raw_token,
    )


async def resend_verification_email(
    db: AsyncSession,
    email: str,
):
    """Public resend. Always returns the same message to avoid email
    enumeration; only actually sends for existing, unverified accounts."""

    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if user is not None and not user.is_email_verified:
        await _issue_verification_otp(db, user)

    return {
        "message": (
            "If an account exists and is not yet verified, "
            "a verification code has been sent."
        )
    }


async def send_verification_email(
    db: AsyncSession,
    user: User,
):
    """
    Generate a verification token and email it to the user (authenticated).
    """

    if user.is_email_verified:
        raise BadRequestError(
            "Email is already verified."
        )

    await _issue_verification_email(db, user)

    return {
        "message": (
            "Verification email sent successfully."
        )
    }


async def verify_email(
    db: AsyncSession,
    token: str,
):
    """
    Verify a user's email address.
    """

    token_hash = hash_token(token)

    # LINK tokens only. A global hash lookup is acceptable for a 256-bit
    # token_urlsafe(32); it is NOT acceptable for a 6-digit OTP, which lives in
    # this same table. Without this filter the endpoint silently became an
    # unthrottled oracle for OTPs, bypassing their attempt cap and rate limit.
    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.token_type == TOKEN_TYPE_LINK,
        )
    )

    verification = result.scalar_one_or_none()

    if verification is None:
        raise BadRequestError(
            "Invalid verification token."
        )

    if verification.used:
        raise BadRequestError(
            "Verification token has already been used."
        )

    if verification.expires_at < datetime.now(UTC):
        raise BadRequestError(
            "Verification token has expired."
        )

    user = await db.get(
        User,
        verification.user_id,
    )

    if user is None:
        raise BadRequestError(
            "User not found."
        )

    user.is_email_verified = True

    verification.used = True

    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=user.id,
        action="verify_email",
        resource="user_account",
        status="success",
    )

    await db.flush()

    return {
        "message": (
            "Email verified successfully."
        )
    }