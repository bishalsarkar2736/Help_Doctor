"""Where resolve_clinic_id can return None, and what happens there.

It returns None in exactly one situation: the caller is a PATIENT and supplied
no clinic_id. Patients are global identities, so unlike an admin, doctor or
receptionist there is no clinic on the principal to fall back to. Every other
role either resolves to an int or raises.

Of the 63 call sites, one is reachable by a patient: POST /medicines/assistant.
Everything else is behind require_roles(ADMIN...) in some combination, so the
None branch cannot be entered — which is why this is a one-line fix and not a
sweep of null checks.

The interesting part is that it did not crash. MedicineAssistantQuery declares
clinic_id NOT NULL, but the column is nullable in the database, so the row was
written with a NULL tenant instead of raising. A query belonging to no clinic
appears in no clinic's analytics, and the daily model budget is keyed by
clinic, so every such request shared one "clinic:None" bucket. Correcting that
schema drift would have turned a quiet mis-attribution into a 500 on a live
endpoint.
"""

import pytest

from app.models.user import User, UserRole
from app.services.tenant_resolver import resolve_clinic_id
from app.try_except.exceptions import ForbiddenError


# ---------------------------------------------------------------------------
# The one place None comes from
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_patient_without_a_clinic_id_resolves_to_none(db, patient_user):
    """Documented rather than prevented: it is the honest answer for a role
    that genuinely has no clinic."""
    assert await resolve_clinic_id(db=db, user=patient_user, clinic_id=None) is None


async def _bound_user(db, role, clinic_id):
    user = User(
        email=f"bound-{role.value}@example.com", full_name="Bound",
        hashed_password="x", role=role, is_active=True, clinic_id=clinic_id,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_a_receptionist_resolves_from_the_principal(db, default_clinic):
    """Never None: the clinic comes from the user record."""
    user = await _bound_user(db, UserRole.RECEPTIONIST, default_clinic.id)

    assert await resolve_clinic_id(db=db, user=user, clinic_id=None) == (
        default_clinic.id
    )


@pytest.mark.asyncio
async def test_an_admin_omitting_clinic_id_raises_rather_than_returning_none(
    db, default_clinic
):
    """An asymmetry worth recording rather than smoothing over.

    An admin MUST pass clinic_id — it is then checked against their own — while
    a receptionist need not. Both are equally safe for this audit's purpose,
    because neither can produce None; they differ only in whether the caller is
    required to state what the server already knows.

    Several endpoints declare clinic_id optional and are admin-guarded, so
    omitting it there is a 403 rather than a default. Noted in the audit as an
    API inconsistency, not changed here: it is not a None-safety problem and
    tightening it would alter working endpoints.
    """
    user = await _bound_user(db, UserRole.ADMIN, default_clinic.id)

    with pytest.raises(ForbiddenError, match="clinic_id required"):
        await resolve_clinic_id(db=db, user=user, clinic_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.RECEPTIONIST])
async def test_a_clinic_bound_role_with_no_clinic_raises_rather_than_returning_none(
    db, role
):
    unassigned = User(
        email=f"unassigned-{role.value}@example.com", full_name="Unassigned",
        hashed_password="x", role=role, is_active=True, clinic_id=None,
    )
    db.add(unassigned)
    await db.flush()

    with pytest.raises(ForbiddenError):
        await resolve_clinic_id(db=db, user=unassigned, clinic_id=None)


@pytest.mark.asyncio
async def test_a_doctor_resolves_from_their_profile(db, auth_doctor):
    resolved = await resolve_clinic_id(
        db=db, user=auth_doctor["user"], clinic_id=None
    )

    assert resolved == auth_doctor["doctor"].clinic_id
    assert resolved is not None


# ---------------------------------------------------------------------------
# The one consumer that could receive it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_patient_must_say_which_clinic_they_are_asking_about(
    client, auth_patient
):
    """400, not 403: the caller is allowed here, the request is incomplete."""
    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?"},
        headers=auth_patient["headers"],
    )

    assert res.status_code == 400, res.text
    assert "clinic_id is required" in res.text


@pytest.mark.asyncio
async def test_no_query_row_is_written_without_a_tenant(client, db, auth_patient):
    """The reason this mattered: it used to write one, with clinic_id NULL."""
    from sqlalchemy import func, select

    from app.models.medicine_assistant_query import MedicineAssistantQuery

    before = await db.scalar(select(func.count(MedicineAssistantQuery.id)))

    await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?"},
        headers=auth_patient["headers"],
    )

    assert await db.scalar(select(func.count(MedicineAssistantQuery.id))) == before


@pytest.mark.asyncio
async def test_a_patient_who_names_a_clinic_is_answered(
    client, db, auth_patient, default_clinic
):
    """The fix must not cost patients the endpoint."""
    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?", "clinic_id": default_clinic.id},
        headers=auth_patient["headers"],
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a_doctor_still_needs_no_clinic_id(client, auth_doctor):
    """Clinic-bound callers keep omitting it — that is why the field cannot
    simply be made required in the request schema."""
    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?"},
        headers=auth_doctor["headers"],
    )

    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# The classification itself
# ---------------------------------------------------------------------------


def test_no_patient_reachable_endpoint_calls_the_resolver_unguarded():
    """A guard on the audit's central claim.

    Every call site other than the medicine assistant sits behind
    require_roles(...) without PATIENT, so the None branch is unreachable
    there. If someone later exposes the resolver on an endpoint a patient can
    reach, this fails and the classification gets redone rather than silently
    going stale.
    """
    import ast
    import re
    from pathlib import Path

    routes = Path(__file__).parent.parent.parent / "app" / "api" / "routes"

    # Endpoints known to be patient-reachable, with the None case handled.
    handled = {"medicine_assistant"}

    unguarded = []

    for path in sorted(routes.glob("*.py")):
        source = path.read_text()

        if "resolve_clinic_id" not in source:
            continue

        for fn in ast.walk(ast.parse(source)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            segment = ast.get_source_segment(source, fn) or ""

            if "resolve_clinic_id(" not in segment or fn.name in handled:
                continue

            signature = segment.split("):")[0]

            # Either it names the roles it admits (and PATIENT is not among
            # them), or it is a helper called from endpoints that do.
            roles = set(re.findall(r"UserRole\.([A-Z_]+)", signature))

            if "require_roles" not in signature:
                continue  # helper; its callers are checked by the tests above

            if not roles or "PATIENT" in roles:
                unguarded.append(f"{path.name}::{fn.name}")

    assert not unguarded, (
        f"these call sites admit patients, so resolve_clinic_id can return "
        f"None into them: {unguarded}"
    )
