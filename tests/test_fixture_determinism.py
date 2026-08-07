"""The test fixtures must not guess which tenant a row belongs to.

appointment_factory and prescription_factory used to resolve the clinic with

    clinic = await db.scalar(select(Clinic))

which is not a lookup, it is a coin flip: no WHERE and no ORDER BY, so Postgres
returns whichever row it likes — commonly insertion order, but nothing promises
that, and a VACUUM or a plan change can reorder it.

It read as correct because most tests build exactly one clinic. That makes it
the worst kind of defect: invisible until a test builds a second one, and then
wrong in the direction that HIDES failures rather than causing them. A
cross-tenant isolation test whose two clinics collapse into one asserts nothing
and still passes green.

That matters more now than it did. Appointments are what make a patient
visible to a clinic, so an appointment written to an arbitrary tenant decides
the outcome of the scoping tests in tests/api/test_patient_search_scoping.py.

These tests build several clinics on purpose, and arrange for the arbitrary
answer to be the WRONG one, so they fail against the old implementation rather
than merely describing the new one.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Gender, Patient
from app.models.prescription import Prescription
from app.models.user import User, UserRole


@pytest.fixture
async def crowded(db, default_clinic):
    """Several clinics, with the doctor deliberately NOT in the first one.

    `default_clinic` is created first, so an unfiltered `select(Clinic)`
    reaches for it. The doctor is put in the last clinic instead, which is what
    turns "arbitrary" into "wrong" and lets these tests detect it.
    """
    clinics = [default_clinic]

    for name in ("Second Clinic", "Third Clinic"):
        clinic = Clinic(name=name, status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")
        db.add(clinic)
        clinics.append(clinic)

    await db.flush()

    home = clinics[-1]

    doctor_user = User(
        email="determinism-doc@example.com",
        full_name="Dr Determinism",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=home.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=home.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    patient_user = User(
        email="determinism-patient@example.com",
        full_name="Determinism Patient",
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(patient_user)
    await db.flush()

    db.add(
        Patient(
            user_id=patient_user.id,
            phone="+8801900000001",
            address="Dhaka",
            date_of_birth=date(1990, 1, 1),
            gender=Gender.MALE,
        )
    )
    await db.flush()

    return {
        "clinics": clinics,
        "home": home,
        "doctor": doctor,
        "patient": patient_user,
    }


# ---------------------------------------------------------------------------
# The clinic comes from the doctor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_appointment_lands_in_its_doctors_clinic(
    db, crowded, appointment_factory
):
    appointment = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    assert appointment.clinic_id == crowded["doctor"].clinic_id


@pytest.mark.asyncio
async def test_the_arbitrary_answer_would_have_been_the_wrong_one(
    db, crowded, appointment_factory
):
    """What makes the test above meaningful rather than tautological.

    If the unfiltered query happened to return the doctor's own clinic, the
    assertion would pass under both implementations and prove nothing. This
    asserts the two genuinely differ, so the fixture above is a real test.
    """
    arbitrary = await db.scalar(select(Clinic))

    assert arbitrary.id != crowded["doctor"].clinic_id, (
        "the unfiltered query returned the doctor's own clinic, so these "
        "tests cannot distinguish the implementations — rework the fixture"
    )

    appointment = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    assert appointment.clinic_id != arbitrary.id


@pytest.mark.asyncio
async def test_the_result_does_not_depend_on_how_many_clinics_exist(
    db, crowded, appointment_factory
):
    """Determinism, stated as the property it is.

    Adding unrelated clinics between two identical calls must not change what
    they produce. Under the old implementation it could.
    """
    first = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=utc_now() + timedelta(hours=1),
    )

    for name in ("Fourth Clinic", "Fifth Clinic"):
        db.add(Clinic(name=name, status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka"))

    await db.flush()

    second = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=utc_now() + timedelta(hours=2),
    )

    assert first.clinic_id == second.clinic_id == crowded["doctor"].clinic_id


@pytest.mark.asyncio
async def test_repeated_calls_agree(db, crowded, appointment_factory):
    """No ordering dependence between identical calls."""
    landed = set()

    for hour in range(1, 5):
        appointment = await appointment_factory(
            patient_id=crowded["patient"].id,
            doctor_id=crowded["doctor"].id,
            status=AppointmentStatus.CONFIRMED,
            scheduled_at=utc_now() + timedelta(hours=hour),
        )
        landed.add(appointment.clinic_id)

    assert landed == {crowded["doctor"].clinic_id}


# ---------------------------------------------------------------------------
# An explicit clinic wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_clinic_is_used_as_given(
    db, crowded, appointment_factory
):
    """For the tests that need an appointment somewhere other than the
    doctor's own clinic — a state worth being able to construct on purpose."""
    elsewhere = crowded["clinics"][1]

    appointment = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
        clinic_id=elsewhere.id,
    )

    assert appointment.clinic_id == elsewhere.id


# ---------------------------------------------------------------------------
# When the tenant cannot be determined, say so
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_doctor_and_no_clinic_fails_loudly(db, crowded, appointment_factory):
    """The behaviour the old code replaced with a guess."""
    with pytest.raises(AssertionError, match="cannot tell which clinic"):
        await appointment_factory(
            patient_id=crowded["patient"].id,
            doctor_id=None,
            status=AppointmentStatus.CONFIRMED,
        )


@pytest.mark.asyncio
async def test_an_unknown_doctor_fails_loudly(db, crowded, appointment_factory):
    with pytest.raises(AssertionError, match="not a Doctor row"):
        await appointment_factory(
            patient_id=crowded["patient"].id,
            doctor_id=987654,
            status=AppointmentStatus.CONFIRMED,
        )


@pytest.mark.asyncio
async def test_a_doctor_with_no_clinic_fails_loudly(
    db, crowded, appointment_factory
):
    """Doctor.clinic_id is nullable, so this is a reachable state."""
    stray_user = User(
        email="stray-doc@example.com",
        full_name="Dr Stray",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(stray_user)
    await db.flush()

    stray = Doctor(
        user_id=stray_user.id,
        clinic_id=None,
        specialization="Medicine",
        experience_years=1,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(stray)
    await db.flush()

    with pytest.raises(AssertionError, match="not assigned to a clinic"):
        await appointment_factory(
            patient_id=crowded["patient"].id,
            doctor_id=stray.id,
            status=AppointmentStatus.CONFIRMED,
        )


# ---------------------------------------------------------------------------
# A prescription and its appointment never disagree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_prescription_lands_in_its_doctors_clinic(
    db, crowded, prescription_factory
):
    prescription = await prescription_factory(
        doctor_id=crowded["doctor"].id,
        patient_id=crowded["patient"].id,
    )

    assert prescription.clinic_id == crowded["doctor"].clinic_id


@pytest.mark.asyncio
async def test_a_prescription_matches_the_appointment_it_was_written_at(
    db, crowded, prescription_factory
):
    """The inconsistency the arbitrary clinic allowed.

    The appointment was derived and the prescription was picked at random, so
    the two could sit in different tenants — a state the application cannot
    produce.
    """
    prescription = await prescription_factory(
        doctor_id=crowded["doctor"].id,
        patient_id=crowded["patient"].id,
    )

    appointment_clinic = await db.scalar(
        select(Appointment.clinic_id).where(
            Appointment.id == prescription.appointment_id
        )
    )

    assert prescription.clinic_id == appointment_clinic


@pytest.mark.asyncio
async def test_a_prescription_follows_an_explicitly_given_appointment(
    db, crowded, appointment_factory, prescription_factory
):
    """Even when that appointment is somewhere unexpected."""
    elsewhere = crowded["clinics"][1]

    appointment = await appointment_factory(
        patient_id=crowded["patient"].id,
        doctor_id=crowded["doctor"].id,
        status=AppointmentStatus.IN_CONSULTATION,
        clinic_id=elsewhere.id,
    )

    prescription = await prescription_factory(
        doctor_id=crowded["doctor"].id,
        patient_id=crowded["patient"].id,
        appointment_id=appointment.id,
    )

    assert prescription.clinic_id == elsewhere.id


# ---------------------------------------------------------------------------
# The pattern itself is gone
# ---------------------------------------------------------------------------


def test_no_fixture_selects_a_clinic_without_a_filter():
    """A guard on the shape, not just on these two factories.

    Reintroducing `select(Clinic)` with no WHERE anywhere in conftest brings
    the whole class of defect back, and it would pass every test above.

    Parsed rather than grepped. A regex over the source also matches the
    several places that DISCUSS the pattern in prose — including the docstring
    of the helper that replaced it — and a guard that fails on its own
    explanation gets deleted rather than heeded.
    """
    import ast
    from pathlib import Path

    conftest = Path(__file__).parent / "conftest.py"
    tree = ast.parse(conftest.read_text())

    def is_unfiltered_clinic_select(node) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "select"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "Clinic"
        )

    # `select(Clinic).where(...)` parses as a .where call wrapping the select,
    # so a select that appears in that position is filtered and fine.
    filtered = {
        id(node.func.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"where", "filter", "filter_by"}
        and is_unfiltered_clinic_select(node.func.value)
    }

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if is_unfiltered_clinic_select(node) and id(node) not in filtered
    ]

    assert not offenders, (
        f"conftest.py selects an arbitrary Clinic at line(s) {offenders}. "
        f"Derive the tenant from the doctor, or take it explicitly."
    )
