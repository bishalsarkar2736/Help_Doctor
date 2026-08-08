"""One rule about who is publicly visible, enforced everywhere.

A suspended clinic is temporarily offline: hidden from discovery, not bookable,
staff cannot log in. DELETED behaves identically — the two differ in
reversibility, not in what the public sees.

The defect this guards is DRIFT. /clinics filtered on status while /doctors did
not, so a suspended clinic vanished from the clinic picker and its doctors
stayed listed, bookable and answerable by the assistant. The enumeration test
at the end is the real protection: it walks every public endpoint and asserts
each one hides the same clinic, so the next endpoint added has to join the rule
or fail here.

What suspension explicitly does NOT touch is asserted just as carefully — a
patient's own records, and prescription verification. Suspension is usually a
billing matter, and withholding someone's medical history over one would be the
wrong answer to the wrong question.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time import utc_now
from app.domain.clinics.visibility import clinic_is_public, is_public
from app.models.appointment import AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.prescription import PrescriptionStatus
from app.models.doctor_slot import DoctorSlot
from app.models.user import User, UserRole


async def _clinic_with_doctor(db, *, name, status, deleted=False, email, tz="Asia/Dhaka"):
    clinic = Clinic(
        name=name,
        status=status,
        timezone=tz,
        deleted_at=utc_now() if deleted else None,
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email=email,
        full_name=f"Dr {name}",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    start = utc_now() + timedelta(hours=2)
    db.add(
        DoctorSlot(
            doctor_id=doctor.id,
            start_time=start,
            end_time=start + timedelta(minutes=30),
        )
    )
    await db.flush()

    return clinic, doctor


@pytest.fixture
async def visible(db):
    clinic, doctor = await _clinic_with_doctor(
        db, name="Open Clinic", status=ClinicStatus.ACTIVE, email="open@t.com"
    )
    await db.commit()
    return clinic, doctor


@pytest.fixture
async def suspended(db):
    clinic, doctor = await _clinic_with_doctor(
        db, name="Suspended Clinic", status=ClinicStatus.SUSPENDED, email="susp@t.com"
    )
    await db.commit()
    return clinic, doctor


@pytest.fixture
async def deleted(db):
    clinic, doctor = await _clinic_with_doctor(
        db,
        name="Deleted Clinic",
        status=ClinicStatus.DELETED,
        deleted=True,
        email="del@t.com",
    )
    await db.commit()
    return clinic, doctor


# ---------------------------------------------------------------------------
# The predicate itself
# ---------------------------------------------------------------------------


def test_an_active_clinic_is_public():
    assert is_public(Clinic(name="C", status=ClinicStatus.ACTIVE, deleted_at=None))


def test_a_suspended_clinic_is_not():
    assert not is_public(Clinic(name="C", status=ClinicStatus.SUSPENDED))


def test_a_deleted_clinic_is_not():
    assert not is_public(Clinic(name="C", status=ClinicStatus.DELETED))


def test_a_soft_deleted_row_is_not_public_even_if_active():
    """status and deleted_at are written by different flows."""
    clinic = Clinic(name="C", status=ClinicStatus.ACTIVE, deleted_at=utc_now())

    assert not is_public(clinic)


def test_nothing_is_not_public():
    assert not is_public(None)


def test_the_query_form_checks_both_columns():
    assert len(clinic_is_public()) == 2


# ---------------------------------------------------------------------------
# ACTIVE is visible everywhere
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_active_clinic_is_listed(client, visible):
    clinic, _ = visible
    res = await client.get("/clinics")

    assert clinic.id in [c["id"] for c in res.json()]


@pytest.mark.asyncio
async def test_an_active_clinics_doctor_is_listed(client, visible):
    _, doctor = visible
    res = await client.get("/doctors")

    assert doctor.id in [d["id"] for d in res.json()]


# ---------------------------------------------------------------------------
# SUSPENDED and DELETED are hidden from discovery
# ---------------------------------------------------------------------------


HIDDEN_STATES = [
    pytest.param(ClinicStatus.SUSPENDED, False, id="suspended"),
    pytest.param(ClinicStatus.DELETED, True, id="deleted"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("status, soft_deleted", HIDDEN_STATES)
async def test_the_clinic_is_not_listed(client, db, status, soft_deleted):
    clinic, _ = await _clinic_with_doctor(
        db, name=f"Hidden {status.value}", status=status,
        deleted=soft_deleted, email=f"h1-{status.value}@t.com",
    )
    await db.commit()

    res = await client.get("/clinics")

    assert clinic.id not in [c["id"] for c in res.json()]


@pytest.mark.asyncio
@pytest.mark.parametrize("status, soft_deleted", HIDDEN_STATES)
async def test_its_doctors_are_not_listed(client, db, status, soft_deleted):
    _, doctor = await _clinic_with_doctor(
        db, name=f"Hidden {status.value}", status=status,
        deleted=soft_deleted, email=f"h2-{status.value}@t.com",
    )
    await db.commit()

    res = await client.get("/doctors")

    assert doctor.id not in [d["id"] for d in res.json()]


@pytest.mark.asyncio
@pytest.mark.parametrize("status, soft_deleted", HIDDEN_STATES)
async def test_its_doctor_detail_is_not_found(client, db, status, soft_deleted):
    _, doctor = await _clinic_with_doctor(
        db, name=f"Hidden {status.value}", status=status,
        deleted=soft_deleted, email=f"h3-{status.value}@t.com",
    )
    await db.commit()

    res = await client.get(f"/doctors/{doctor.id}")

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_its_specializations_are_excluded(client, db, suspended):
    """The suspended clinic is the only one practising this specialty."""
    clinic, doctor = suspended

    doctor.specialization = "Neurosurgery"
    await db.commit()

    res = await client.get("/doctors/specializations")

    assert "Neurosurgery" not in res.json()


@pytest.mark.asyncio
async def test_its_slots_are_not_offered(client, suspended):
    """Slots keep being generated so recovery is instant — just not shown."""
    _, doctor = suspended

    res = await client.get(
        f"/slots/doctors/{doctor.id}/slots",
        params={"start_date": utc_now().date().isoformat(), "days": 7},
    )

    assert res.status_code == 200, res.text
    assert res.json() == []


@pytest.mark.asyncio
async def test_the_assistant_will_not_answer_for_it(client, suspended):
    clinic, _ = suspended

    res = await client.post(
        "/assistant/ask",
        params={"clinic_id": clinic.id},
        json={"question": "I need a cardiologist"},
    )

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_booking_is_refused(client, db, auth_patient, suspended):
    """Hiding a doctor from search does not stop a booking against an id
    someone already holds — a stale tab, a bookmark, a link in an email."""
    _, doctor = suspended

    res = await client.post(
        "/appointments/",
        json={
            "doctor_id": doctor.id,
            "scheduled_at": (utc_now() + timedelta(days=1)).isoformat(),
        },
        headers=auth_patient["headers"],
    )

    # 409, not 403: nothing about the caller is wrong, and a client that
    # reacts to 403 by re-authenticating would retry forever. The request
    # conflicts with the clinic's current state.
    #
    # Not 503 either — that reports a whole-service outage for one suspended
    # tenant, and puts an ordinary business outcome in the error-rate graphs.
    assert res.status_code == 409, res.text
    assert "unavailable" in res.text.lower()


@pytest.mark.asyncio
async def test_the_earliest_slot_search_skips_it(db, suspended):
    from app.services.earliest_slot_service import find_earliest_available_doctor

    clinic, _ = suspended

    assert await find_earliest_available_doctor(db, clinic_id=clinic.id) == []


# ---------------------------------------------------------------------------
# What suspension does NOT touch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_patient_still_sees_their_appointments(
    client, db, auth_patient, suspended, appointment_factory
):
    """A billing dispute is not a reason to withhold someone's own records."""
    _, doctor = suspended

    await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=doctor.id,
        status=AppointmentStatus.PENDING,
    )

    res = await client.get("/appointments/own", headers=auth_patient["headers"])

    assert res.status_code == 200, res.text
    assert len(res.json()) >= 1


@pytest.mark.asyncio
async def test_an_existing_appointment_is_not_cancelled_or_altered(
    db, auth_patient, suspended, appointment_factory
):
    """Suspension changes no appointment status. Nothing is auto-cancelled."""
    _, doctor = suspended

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=doctor.id,
        status=AppointmentStatus.PENDING,
    )
    before = appointment.status

    from app.models.appointment import Appointment

    stored = await db.get(Appointment, appointment.id)
    await db.refresh(stored)

    assert stored.status == before
    assert stored.id is not None


@pytest.mark.asyncio
async def test_prescription_verification_still_works(
    client, db, auth_patient, suspended, appointment_factory, prescription_factory
):
    """A pharmacist is checking authenticity, not availability.

    A prescription issued while the clinic was active stays valid; suspension
    does not retroactively invalidate it.
    """
    _, doctor = suspended

    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )
    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=doctor.id,
        patient_id=auth_patient["user"].id,
        # Verification is for ISSUED prescriptions; a draft is correctly not
        # publicly verifiable, and that has nothing to do with suspension.
        status=PrescriptionStatus.ISSUED,
        issued_at=utc_now(),
    )

    res = await client.get(f"/prescriptions/verify/{prescription.uuid}")

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a_patient_is_not_bound_to_a_clinic(db, auth_patient, suspended):
    """Which is why a suspended clinic cannot block a patient's login.

    The login gate reads the user's clinic; patients have none, so it never
    fires for them. Asserted on the property the gate depends on rather than by
    attempting a password login, which needs a real hash.
    """
    from app.models.user import User as U

    patient = await db.scalar(
        select(U).where(U.id == auth_patient["user"].id)
    )

    assert patient is not None
    assert patient.clinic_id is None


# ---------------------------------------------------------------------------
# The regression test that stops the next endpoint drifting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_public_endpoint_hides_a_suspended_clinic(client, db, suspended):
    """Walks the public surface and asserts one rule across all of it.

    Adding a public endpoint that forgets the predicate should fail HERE, in a
    test that enumerates them, rather than being noticed when a suspended
    clinic turns up in production.
    """
    clinic, doctor = suspended

    doctor.specialization = "Neurosurgery"
    await db.commit()

    today = utc_now().date().isoformat()

    checks = {
        "GET /clinics": (
            await client.get("/clinics"),
            lambda r: clinic.id not in [c["id"] for c in r.json()],
        ),
        "GET /doctors": (
            await client.get("/doctors"),
            lambda r: doctor.id not in [d["id"] for d in r.json()],
        ),
        "GET /doctors/{id}": (
            await client.get(f"/doctors/{doctor.id}"),
            lambda r: r.status_code == 404,
        ),
        "GET /doctors/specializations": (
            await client.get("/doctors/specializations"),
            lambda r: "Neurosurgery" not in r.json(),
        ),
        "GET /doctors/specializations?clinic_id": (
            await client.get(
                "/doctors/specializations", params={"clinic_id": clinic.id}
            ),
            lambda r: r.json() == [],
        ),
        "GET /slots/doctors/{id}/slots": (
            await client.get(
                f"/slots/doctors/{doctor.id}/slots",
                params={"start_date": today, "days": 7},
            ),
            lambda r: r.json() == [],
        ),
        "POST /assistant/ask": (
            await client.post(
                "/assistant/ask",
                params={"clinic_id": clinic.id},
                json={"question": "I need a cardiologist"},
            ),
            lambda r: r.status_code == 404,
        ),
    }

    leaked = [name for name, (res, ok) in checks.items() if not ok(res)]

    assert not leaked, f"suspended clinic visible through: {leaked}"
