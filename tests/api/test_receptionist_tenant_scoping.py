"""A receptionist may only reach their own clinic.

resolve_clinic_id used to group RECEPTIONIST with PATIENT under "not
clinic-scoped" and return the caller's own value unchanged, so a receptionist
could point any endpoint at any tenant by editing a query string.

Two endpoints admitted that role and passed the parameter straight through:

    GET /appointments/search?clinic_id=<any>   -> another clinic's roster
    GET /prescriptions/search?clinic_id=<any>  -> another clinic's prescriptions

Both returned patient names. The prescription one also returned medication,
which is about as identifying as clinical data gets.

Neither endpoint's existing test file builds a second clinic, which is why this
survived: with one tenant in the fixture, a query that ignores the tenant looks
exactly like one that respects it. So these tests build two.
"""

from datetime import timedelta

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Gender, Patient
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.tenant_resolver import resolve_clinic_id
from app.try_except.exceptions import ForbiddenError


@pytest.fixture
async def two_clinics(db, default_clinic):
    """The receptionist's own clinic, and somebody else's with data in it."""
    theirs = Clinic(name="Other Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(theirs)
    await db.flush()

    doctor_user = User(
        email="other-doc@example.com", full_name="Dr Other", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=theirs.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=theirs.id, specialization="Oncology",
        experience_years=3, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    patient_user = User(
        email="other-patient@example.com", full_name="Other Clinic Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient_user)
    await db.flush()

    db.add(Patient(
        user_id=patient_user.id, phone="+8801777000222", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    start = utc_now() + timedelta(hours=3)
    appointment = Appointment(
        patient_id=patient_user.id, doctor_id=doctor.id, clinic_id=theirs.id,
        scheduled_at=start, status=AppointmentStatus.CONFIRMED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    db.add(Prescription(
        appointment_id=appointment.id, doctor_id=doctor.id,
        patient_id=patient_user.id, status=PrescriptionStatus.ISSUED,
        notes="Confidential regimen", issued_at=utc_now(),
        clinic_id=theirs.id, revision_number=1, is_latest_revision=True,
    ))

    receptionist = User(
        email="own-clinic-recep@example.com", full_name="Receptionist",
        hashed_password="x", role=UserRole.RECEPTIONIST, is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(receptionist)
    await db.flush()
    await db.commit()

    token = create_access_token(
        data={"sub": str(receptionist.id), "role": UserRole.RECEPTIONIST.value}
    )

    return {
        "ours": default_clinic,
        "theirs": theirs,
        "receptionist": receptionist,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# ---------------------------------------------------------------------------
# The endpoints that leaked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_search_cannot_be_pointed_at_another_clinic(
    client, two_clinics
):
    res = await client.get(
        "/appointments/search",
        params={"clinic_id": two_clinics["theirs"].id},
        headers=two_clinics["headers"],
    )

    assert res.status_code == 403, (
        f"a receptionist read another clinic's roster: {res.text[:300]}"
    )


@pytest.mark.asyncio
async def test_prescription_search_cannot_be_pointed_at_another_clinic(
    client, two_clinics
):
    res = await client.get(
        "/prescriptions/search",
        params={"clinic_id": two_clinics["theirs"].id},
        headers=two_clinics["headers"],
    )

    assert res.status_code == 403, (
        f"a receptionist read another clinic's prescriptions: {res.text[:300]}"
    )


@pytest.mark.asyncio
async def test_no_patient_name_appears_in_either_response(client, two_clinics):
    """Asserted on the body, not only the status code.

    A 403 that still rendered the row would be a leak with a misleading label,
    and the failure this replaces returned 200 with the name in it.
    """
    for path in ("/appointments/search", "/prescriptions/search"):
        res = await client.get(
            path,
            params={"clinic_id": two_clinics["theirs"].id},
            headers=two_clinics["headers"],
        )

        assert "Other Clinic Patient" not in res.text, path
        assert "Confidential regimen" not in res.text, path


@pytest.mark.asyncio
async def test_the_receptionist_still_sees_their_own_clinic(client, two_clinics):
    """The fix must not cost them the job they actually do."""
    res = await client.get(
        "/appointments/search",
        params={"clinic_id": two_clinics["ours"].id},
        headers=two_clinics["headers"],
    )

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_both_routes_still_require_the_parameter(client, two_clinics):
    """Documenting the contract rather than changing it.

    Both routes declare clinic_id as required, so omitting it is a 422 from
    FastAPI before any of this code runs. The resolver itself tolerates an
    omission — see test_an_omitted_clinic_id_resolves_from_the_principal — so
    these could drop the parameter now that the principal decides the answer.
    Left alone: it is validated against the principal, so keeping it costs
    nothing and changing a public route signature is not part of a security
    fix.
    """
    for path in ("/appointments/search", "/prescriptions/search"):
        res = await client.get(path, headers=two_clinics["headers"])

        assert res.status_code == 422, path


# ---------------------------------------------------------------------------
# The resolver itself, where the defect lived
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_supplied_clinic_id_is_never_the_answer(db, two_clinics):
    with pytest.raises(ForbiddenError):
        await resolve_clinic_id(
            db=db,
            user=two_clinics["receptionist"],
            clinic_id=two_clinics["theirs"].id,
        )


@pytest.mark.asyncio
async def test_a_matching_clinic_id_is_accepted(db, two_clinics):
    resolved = await resolve_clinic_id(
        db=db,
        user=two_clinics["receptionist"],
        clinic_id=two_clinics["ours"].id,
    )

    assert resolved == two_clinics["ours"].id


@pytest.mark.asyncio
async def test_an_omitted_clinic_id_resolves_from_the_principal(db, two_clinics):
    resolved = await resolve_clinic_id(
        db=db, user=two_clinics["receptionist"], clinic_id=None
    )

    assert resolved == two_clinics["ours"].id


@pytest.mark.asyncio
async def test_a_receptionist_with_no_clinic_is_refused(db, two_clinics):
    """Previously this returned whatever the caller asked for."""
    stray = User(
        email="stray-recep@example.com", full_name="Stray", hashed_password="x",
        role=UserRole.RECEPTIONIST, is_active=True, clinic_id=None,
    )
    db.add(stray)
    await db.flush()

    with pytest.raises(ForbiddenError, match="not assigned to clinic"):
        await resolve_clinic_id(
            db=db, user=stray, clinic_id=two_clinics["theirs"].id
        )


@pytest.mark.asyncio
async def test_a_patient_is_still_not_clinic_bound(db, two_clinics, patient_user):
    """Deliberately unchanged, and separated from the receptionist branch.

    Patients are global identities, so there is no clinic on the principal to
    derive from. The medicine assistant is the only caller on this path, where
    clinic_id tags the query log rather than granting access.
    """
    resolved = await resolve_clinic_id(
        db=db, user=patient_user, clinic_id=two_clinics["theirs"].id
    )

    assert resolved == two_clinics["theirs"].id
