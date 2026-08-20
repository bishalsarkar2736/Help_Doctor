"""Which clinic a request is operating inside.

The AI scheduling assistant is multi-tenant and read-only, and every query it
makes has to be scoped to one clinic. This is the single place that decides
which one, so the assistant depends on the ANSWER and not on how it was
reached.

That indirection is the point. Subdomain routing (abcclinic.helpdoctor.com)
needs wildcard DNS and a wildcard certificate, neither of which exists yet.
Building the assistant against the Host header would couple a feature that
could ship today to infrastructure that cannot. When subdomains do arrive, a
strategy is added below and nothing that calls this changes.

RESOLUTION ORDER
----------------
1. An explicit clinic_id on the request.
2. The clinic the authenticated user belongs to.
3. A development header, outside production only.

There is deliberately no fallback. A request that resolves to nothing is a 404,
never "the first clinic" and never an unscoped query — a tenant boundary that
degrades to "search everything" is worse than one that fails.

WHAT COUNTS AS RESOLVABLE
-------------------------
Only an ACTIVE clinic that has not been soft-deleted. A suspended clinic has
had its users' access revoked, and answering questions about its doctors and
opening hours would route patients to a practice that is not operating.
"""

from fastapi import Depends, Header, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.postgres import get_db
from app.domain.clinics.visibility import clinic_is_public
from app.domain.clinics.subdomain import subdomain_from_host
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.user import User, UserRole
from app.security.jwt import get_current_user_optional
from app.try_except.exceptions import ForbiddenError, NotFoundError

# The header name is kept even though only the id form is honoured today.
# Resolving a subdomain needs a column on clinics that deliberately does not
# exist yet: minting one would hand every tenant a public identity for a
# routing scheme that is not deployed, and a subdomain is not something that
# can be quietly changed later.
DEV_CLINIC_ID_HEADER = "X-Clinic-ID"


async def load_active_clinic(db: AsyncSession, clinic_id: int) -> Clinic | None:
    """The clinic, if it exists and is open for business."""
    # The shared predicate, so the assistant, the directory and booking cannot
    # disagree about whether a clinic is open.
    return await db.scalar(
        select(Clinic).where(Clinic.id == clinic_id, *clinic_is_public())
    )


async def clinic_id_for_user(db: AsyncSession, user: User) -> int | None:
    """The clinic an authenticated user belongs to, if any.

    Patients are not bound to a clinic anywhere in the schema, so they resolve
    to nothing here and must identify the clinic explicitly. That is a real
    gap, not an oversight to route around: guessing a patient's clinic from
    their appointment history would pick a tenant on their behalf.
    """
    if user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        return user.clinic_id

    if user.role == UserRole.DOCTOR:
        return await db.scalar(
            select(Doctor.clinic_id).where(Doctor.user_id == user.id)
        )

    return None


async def clinic_for_host(db: AsyncSession, host: str | None) -> Clinic | None:
    """The clinic a Host header names, if it names one that is open.

    Goes through load_active_clinic like every other candidate, so a suspended
    or soft-deleted clinic is not reachable by hostname either — the shared
    clinic_is_public() predicate decides, not a second rule that could drift.
    """
    subdomain = subdomain_from_host(host, get_settings().CLINIC_BASE_DOMAIN)

    if subdomain is None:
        return None

    return await db.scalar(
        select(Clinic).where(
            func.lower(Clinic.subdomain) == subdomain,
            *clinic_is_public(),
        )
    )


async def resolve_clinic_context(
    db: AsyncSession,
    *,
    clinic_id: int | None = None,
    user: User | None = None,
    dev_clinic_id: int | None = None,
    host: str | None = None,
) -> Clinic:
    """The clinic this request operates inside, or 404.

    `dev_clinic_id` comes from a header and is ignored in production, where the
    only acceptable sources are the request itself and the authenticated user.
    Left active it would let any caller name any tenant.
    """
    host_clinic = await clinic_for_host(db, host)

    principal_clinic_id = (
        await clinic_id_for_user(db, user) if user is not None else None
    )

    # THE HOST IS A HINT, NEVER A GRANT.
    #
    # A signed-in user reaching clinic-b.example.com is asking for a tenant
    # they do not belong to. The answer is a refusal, not a quiet switch to
    # whichever clinic the hostname named: silently re-scoping the request
    # would let anyone move a session between tenants by editing a URL, which
    # is the same defect the receptionist branch of resolve_clinic_id once had.
    #
    # Only checked when the principal HAS a clinic. Patients and receptionists
    # resolve to None here (see clinic_id_for_user), and a caller with no
    # tenant of their own contradicts nothing.
    if (
        host_clinic is not None
        and principal_clinic_id is not None
        and principal_clinic_id != host_clinic.id
    ):
        raise ForbiddenError(
            "This host belongs to a different clinic than your account"
        )

    candidates = [clinic_id]

    if user is not None:
        candidates.append(principal_clinic_id)

    # Below the principal on purpose. A signed-in user's own clinic is the
    # better answer, and the check above has already established that the two
    # agree whenever both exist — so the ordering only decides which is
    # consulted first, never which tenant wins a disagreement.
    if host_clinic is not None:
        candidates.append(host_clinic.id)

    if get_settings().ENV != "production":
        candidates.append(dev_clinic_id)

    for candidate in candidates:
        if candidate is None:
            continue

        clinic = await load_active_clinic(db, candidate)

        if clinic is not None:
            return clinic

        # Stop at the first candidate that was offered and did not resolve.
        # Falling through to the next would silently answer for a different
        # tenant than the caller named.
        break

    raise NotFoundError("Clinic not found")


async def require_clinic(
    request: Request,
    clinic_id: int | None = Query(default=None),
    x_clinic_id: int | None = Header(default=None, alias=DEV_CLINIC_ID_HEADER),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> Clinic:
    """FastAPI dependency for any route that must run inside one clinic.

    Public on purpose: the assistant answers questions a clinic already
    publishes — which doctors practise there, when they are free, the address
    and the opening hours. It exposes nothing patient-specific, so requiring a
    login would block the visitors it exists for.

    The resolved clinic is attached to request.state so anything further down
    the request can read it without resolving a second time and risking a
    different answer.
    """
    # Previously read from request.state.user, which nothing ever sets — so the
    # principal was always None here and the user branch below was unreachable
    # through this dependency. An optional dependency supplies it without
    # requiring a token, keeping the endpoint open to the visitors it exists
    # for while making the Host/principal agreement check possible at all.
    clinic = await resolve_clinic_context(
        db,
        clinic_id=clinic_id,
        user=user,
        dev_clinic_id=x_clinic_id,
        host=request.headers.get("host"),
    )

    request.state.clinic = clinic

    return clinic
