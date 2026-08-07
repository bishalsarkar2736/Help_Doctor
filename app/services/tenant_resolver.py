"""Which clinic a request acts on.

THE RULE
--------
The tenant comes from the authenticated principal. A caller-supplied clinic_id
is only ever CHECKED against it, never trusted as the answer.

Staff roles are bound to one clinic, so for them this function is an
authorisation decision, and getting it wrong is a cross-tenant data breach
rather than a bug.

WHAT WENT WRONG BEFORE
----------------------
RECEPTIONIST was grouped with PATIENT under "not clinic-scoped" and the branch
returned the caller's own value unchanged:

    if user.role in {UserRole.PATIENT, UserRole.RECEPTIONIST}:
        return clinic_id

A receptionist could therefore point any endpoint at any tenant by editing a
query string. Two endpoints admitted that role and passed the parameter
straight through — /appointments/search and /prescriptions/search — so a
receptionist at one clinic could read another clinic's appointments (patient
names and emails) and prescriptions (patient, doctor, medication).

Receptionists ARE clinic-scoped: they work at a desk, in a building. The
grouping was the defect, so the roles are separated here rather than patched at
the call sites — there are 63 of those, and the next one added would have
inherited the same hole.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor import Doctor
from app.models.user import User, UserRole
from app.try_except.exceptions import ForbiddenError


async def resolve_clinic_id(
    db: AsyncSession,
    user: User,
    clinic_id: int | None = None,
) -> int | None:
    """The clinic this user may act on.

    Returns None only for PATIENT, who is not clinic-bound — see that branch.
    Every staff role returns an int or raises.
    """

    # -------------------------
    # ADMIN: bound to one clinic
    # -------------------------
    if user.role == UserRole.ADMIN:
        if not user.clinic_id:
            raise ForbiddenError("Admin not assigned to clinic")

        if clinic_id is None:
            raise ForbiddenError("clinic_id required for admin")

        if clinic_id is not None and clinic_id != user.clinic_id:
            raise ForbiddenError("Admin not authorized for this clinic")

        return user.clinic_id

    # -------------------------
    # DOCTOR: from doctor profile
    # -------------------------
    if user.role == UserRole.DOCTOR:
        doctor = await db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )
        if not doctor:
            raise ForbiddenError("Doctor profile not found")

        if not doctor.clinic_id:
            raise ForbiddenError("Doctor not assigned to clinic")

        if clinic_id is not None and clinic_id != doctor.clinic_id:
            raise ForbiddenError("Doctor not authorized for this clinic")

        return doctor.clinic_id

    # -------------------------
    # RECEPTIONIST: bound to one clinic, exactly like an admin
    # -------------------------
    if user.role == UserRole.RECEPTIONIST:
        if not user.clinic_id:
            raise ForbiddenError("Receptionist not assigned to clinic")

        # Rejected rather than quietly re-scoped. A mismatch is either an
        # attempt to reach another tenant or a client bug, and both are worth
        # surfacing — the frontend sends the receptionist's own clinic_id, so
        # this cannot fire on legitimate use.
        #
        # clinic_id is NOT required to be present, unlike for admins: omitting
        # it is unambiguous now that the answer comes from the principal.
        if clinic_id is not None and clinic_id != user.clinic_id:
            raise ForbiddenError("Receptionist not authorized for this clinic")

        return user.clinic_id

    # -------------------------
    # PATIENT: genuinely not clinic-bound
    # -------------------------
    if user.role == UserRole.PATIENT:
        # Patients are global identities — the same person may be treated at
        # several clinics — so there is no clinic on the principal to derive
        # from, and the supplied value is returned as given.
        #
        # This is therefore NOT an authorisation decision, and callers must not
        # treat it as one. The only caller on this path is the medicine
        # assistant, where clinic_id tags the query log and scopes the
        # catalogue; nothing a patient is not already entitled to see sits
        # behind it. Any future patient-reachable endpoint that uses the result
        # as a permission check has to authorise the patient against that
        # clinic itself.
        return clinic_id

    raise ForbiddenError("Invalid role")
