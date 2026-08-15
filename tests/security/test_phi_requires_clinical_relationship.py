"""Staff PHI access must not be unlockable by the staff member themselves.

THE DEFECT
Access to a patient's clinical record is derived from appointments. For ADMIN
and RECEPTIONIST, get_patient_record asks one question:

    does an appointment exist with this patient_id at my clinic?

and POST /appointments/ lets exactly those two roles create such a row for an
arbitrary existing patient_id, bounded only by the DOCTOR belonging to the
caller's own clinic. So the caller can write the row that authorises their own
read:

    POST /appointments/  {patient_id: <any user>, doctor_id: <my own doctor>}
    GET  /patients/<that user>   -> allergies, medications, chronic
                                    conditions, blood type, address, DOB

user ids are sequential (nextval), so the targets are enumerable — the same
walk-the-ids attack the clinic scoping was added to stop.

appointment_service already names this hazard for the doctor argument:

    "It is also how a treatment relationship comes into existence ... an
     unbounded booking endpoint can manufacture the relationship those checks
     rely on."

That reasoning was applied to WHICH DOCTOR may be named and never to WHICH
PATIENT.

THE RULE PINNED HERE
A booking alone is not a clinical relationship. The relationship begins when
someone other than the booking clerk has acted on it — a doctor confirming, or
the patient paying — which is precisely the set of states the FSM can only
reach after CONFIRMED. PENDING is excluded because a receptionist can create it
unilaterally; CANCELLED is excluded because a call that was called off is not
treatment.

WHY THE READ SIDE AND NOT THE BOOKING SIDE
Booking on behalf must keep working for a first-time patient, who by definition
has no prior relationship. Refusing the booking would break the front desk. So
the booking stays exactly as it is and the READ stops trusting it.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api.routes.patients import get_patient_record
from app.core.time import UTC
from app.models.appointment import AppointmentStatus
from app.models.doctor_availability import DoctorAvailability
from app.models.patient import Patient
from app.services.appointment_service import book_appointment
from app.services.patient_search_service import search_patients
from app.try_except.exceptions import ForbiddenError
from tests.conftest import valid_slot

from datetime import time as dtime


def _slot(days: int = 1) -> datetime:
    return valid_slot(datetime.now(UTC) + timedelta(days=days))


@pytest_asyncio.fixture
async def bookable_doctor(db, auth_doctor):
    """The caller's own clinic's doctor, with open availability.

    The attack uses a doctor the caller is entitled to book with — that is what
    makes it an attack rather than a cross-clinic write, which ac5576c already
    refuses. Availability is wide open so a refusal is never a missing slot.
    """
    for day in range(7):
        db.add(
            DoctorAvailability(
                doctor_id=auth_doctor["doctor"].id,
                day_of_week=day,
                start_time=dtime(0, 0),
                end_time=dtime(23, 59),
                is_available=True,
            )
        )
    await db.flush()
    return auth_doctor["doctor"]


async def _read(db, patient_user_id, caller):
    return await get_patient_record(
        patient_user_id=patient_user_id,
        db=db,
        current_user=caller,
    )


# ---------------------------------------------------------------------------
# 1 + 2. The escalation itself: booking must not unlock the record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_receptionist_cannot_unlock_a_record_by_booking(
    db, patient_user, auth_receptionist, bookable_doctor
):
    """THE CORE PROPERTY. The booking is allowed; the read is not."""

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=bookable_doctor.id,
        scheduled_at=_slot(),
        booked_by=auth_receptionist["user"],
    )

    assert appointment.status == AppointmentStatus.PENDING, (
        "fixture assumption: booking creates a PENDING appointment"
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_receptionist["user"])


@pytest.mark.asyncio
async def test_an_admin_cannot_unlock_a_record_by_booking(
    db, patient_user, auth_admin, bookable_doctor
):
    """Same path, the other role that can book on behalf."""

    await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=bookable_doctor.id,
        scheduled_at=_slot(days=2),
        booked_by=auth_admin["user"],
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_admin["user"])


# ---------------------------------------------------------------------------
# 3. The allow-case: a real relationship still reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_confirmed_appointment_grants_the_read(
    db, patient_user, auth_receptionist, auth_doctor, appointment_factory
):
    """CONFIRMED is the narrowest qualifying state: reaching it requires the
    treating doctor to confirm, or the patient to pay — neither of which the
    front desk can do alone."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    record = await _read(db, patient_user.id, auth_receptionist["user"])

    assert record.user_id == patient_user.id


@pytest.mark.asyncio
async def test_a_completed_appointment_grants_the_read(
    db, patient_user, auth_receptionist, auth_doctor, appointment_factory
):
    """The unambiguous case — treatment actually happened."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )

    record = await _read(db, patient_user.id, auth_receptionist["user"])

    assert record.user_id == patient_user.id


# ---------------------------------------------------------------------------
# 4. Cancelled must not manufacture a lasting relationship
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cancelled_appointment_does_not_grant_the_read(
    db, patient_user, auth_receptionist, auth_doctor, appointment_factory
):
    """Otherwise the escalation survives cleanup: book, read, cancel, and the
    access stays open forever because neither predicate filtered on status."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CANCELLED,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_receptionist["user"])


@pytest.mark.asyncio
async def test_a_pending_appointment_does_not_grant_the_read(
    db, patient_user, auth_receptionist, auth_doctor, appointment_factory
):
    """Stated directly, not only through the booking route, so the rule cannot
    be satisfied by a fix that special-cases who created the row."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.PENDING,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_receptionist["user"])


# ---------------------------------------------------------------------------
# 5. The clinic dimension is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_qualifying_appointment_at_another_clinic_does_not_grant_the_read(
    db, patient_user, auth_receptionist, other_clinic_doctor, appointment_factory
):
    """A CONFIRMED appointment is a relationship with the clinic that holds it,
    not with every clinic. The status rule narrows the existing clinic rule; it
    must not replace it."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_receptionist["user"])


# ---------------------------------------------------------------------------
# 6. First-visit booking still works — the workflow this must not break
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_first_visit_booking_still_succeeds(
    db, patient_user, auth_receptionist, bookable_doctor
):
    """The reason the fix is on the read side. A first-time patient has no
    relationship by definition, and reception must still be able to book them.
    """

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=bookable_doctor.id,
        scheduled_at=_slot(days=3),
        booked_by=auth_receptionist["user"],
    )

    assert appointment.id is not None
    assert appointment.patient_id == patient_user.id


@pytest.mark.asyncio
async def test_a_patient_may_still_book_themselves(
    db, patient_user, bookable_doctor
):
    """Self-booking is untouched: patients are global identities."""

    appointment = await book_appointment(
        db=db,
        patient=patient_user,
        doctor_id=bookable_doctor.id,
        scheduled_at=_slot(days=4),
        booked_by=patient_user,
    )

    assert appointment.id is not None


# ---------------------------------------------------------------------------
# 7. Search follows the same relationship rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_does_not_surface_a_pending_only_patient(
    db, patient_user, auth_doctor, auth_receptionist, appointment_factory
):
    """One definition of whose patient this is. If search kept the laxer rule,
    the front desk could still page through everyone it had booked."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.PENDING,
    )

    results = await search_patients(
        db=db,
        clinic_id=auth_receptionist["user"].clinic_id,
        q="",
    )

    assert patient_user.id not in [r.user_id for r in results]


@pytest.mark.asyncio
async def test_search_still_surfaces_a_confirmed_patient(
    db, patient_user, auth_doctor, auth_receptionist, appointment_factory
):
    """The paired allow-case, so the test above cannot pass by search being
    broken outright."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    results = await search_patients(
        db=db,
        clinic_id=auth_receptionist["user"].clinic_id,
        q="",
    )

    assert patient_user.id in [r.user_id for r in results]


@pytest.mark.asyncio
async def test_the_exact_identifier_exception_is_preserved(
    db, patient_user, auth_receptionist
):
    """EXISTING BEHAVIOUR, pinned so this change does not quietly remove it.

    A caller holding a full email already reaches a patient with no
    appointments at all — that is how reception finds someone before booking
    them. It surfaces identity and contact details (PatientSearchOut), never
    the clinical record, and it is deliberately outside the relationship rule.
    """

    results = await search_patients(
        db=db,
        clinic_id=auth_receptionist["user"].clinic_id,
        q=patient_user.email,
    )

    assert patient_user.id in [r.user_id for r in results]


# ---------------------------------------------------------------------------
# 8. Doctor access is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_doctors_own_patient_is_still_readable(
    db, patient_user, auth_doctor, appointment_factory
):
    """The DOCTOR branch has its own, stricter rule — the doctor treats this
    patient, not merely shares a clinic with them. It must keep working."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    record = await _read(db, patient_user.id, auth_doctor["user"])

    assert record.user_id == patient_user.id


@pytest.mark.asyncio
async def test_a_doctor_with_no_relationship_is_still_refused(
    db, patient_user, auth_doctor
):
    """The doctor allow-case above must not be passing for the wrong reason."""

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_doctor["user"])


# ---------------------------------------------------------------------------
# 9. The qualifying set itself
# ---------------------------------------------------------------------------


def test_the_qualifying_statuses_are_exactly_the_post_confirmation_ones():
    """Pins the SET, not just its effects.

    Every member is reachable only once a doctor has confirmed (or the patient
    has paid, which confirms). The two exclusions are the whole point:

      PENDING   — a receptionist creates this alone, by booking.
      CANCELLED — a call that was called off is not treatment, and leaving it
                  in would let the escalation survive its own cleanup.

    A later status added to the enum defaults to NOT granting access, which is
    the safe direction; this test fails loudly so the choice is made
    deliberately rather than inherited.
    """
    from app.domain.policies.patient_access_policy import (
        CLINICAL_RELATIONSHIP_STATUSES,
    )

    assert CLINICAL_RELATIONSHIP_STATUSES == frozenset(
        {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CHECKED_IN,
            AppointmentStatus.WAITING,
            AppointmentStatus.IN_CONSULTATION,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        }
    )

    assert AppointmentStatus.PENDING not in CLINICAL_RELATIONSHIP_STATUSES
    assert AppointmentStatus.CANCELLED not in CLINICAL_RELATIONSHIP_STATUSES


def test_every_phi_surface_uses_the_shared_predicate():
    """Structural, because the hazard is a duplicated rule rather than a wrong
    value: three call sites derived access from appointments, and a fix applied
    to one of them just moves the escalation to the other two.
    """
    import ast
    import pathlib

    modules = [
        "app/api/routes/patients.py",
        "app/services/patient_search_service.py",
        "app/services/patient_history_service.py",
    ]

    offenders = []

    for module in modules:
        tree = ast.parse(pathlib.Path(module).read_text())

        uses_helper = any(
            isinstance(n, ast.Name) and n.id == "clinical_relationship_exists"
            for n in ast.walk(tree)
        )

        if not uses_helper:
            offenders.append(module)

    assert not offenders, (
        "a PHI surface still derives access from appointments without the "
        f"shared status-aware predicate: {offenders}"
    )


# ---------------------------------------------------------------------------
# 10. The doctor rule is its own rule: review before confirming, nothing after
#     cancelling
# ---------------------------------------------------------------------------
#
# WHY THE DOCTOR BRANCH DIFFERS FROM THE DESK'S
# The rule above exists because a receptionist can create the very row that
# authorises their own read. A doctor cannot: booking on behalf is
# RECEPTIONIST/ADMIN only, so a doctor never manufactures their own access.
#
# That difference is what makes PENDING safe here and unsafe there. A doctor
# reviewing a chart BEFORE deciding whether to confirm is the normal order of
# work — requiring CONFIRMED first would invert it, forcing a clinician to
# commit to an appointment before being allowed to look at who it is for.
#
# CANCELLED is the half that does not survive. A visit that was called off is
# not treatment, and leaving it in would mean a single cancelled appointment
# grants one doctor permanent access to that patient's chart. It also closes
# the displaced escalation: reception can put any patient in front of a doctor
# by booking them, and if cancelling left the access behind, that exposure
# would be permanent rather than lasting only as long as the appointment does.


@pytest.mark.asyncio
async def test_a_doctor_may_review_a_pending_appointment(
    db, patient_user, auth_doctor, appointment_factory
):
    """PRE-CONFIRMATION REVIEW. Deliberately allowed, and deliberately not
    allowed for the front desk — see the module docstring."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.PENDING,
    )

    record = await _read(db, patient_user.id, auth_doctor["user"])

    assert record.user_id == patient_user.id


@pytest.mark.asyncio
async def test_a_doctor_cannot_read_through_a_cancelled_appointment(
    db, patient_user, auth_doctor, appointment_factory
):
    """THE CHANGE. A cancelled appointment is not a treatment relationship, and
    must not leave a permanent read behind."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CANCELLED,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_doctor["user"])


@pytest.mark.asyncio
async def test_a_cancelled_appointment_does_not_revoke_a_live_one(
    db, patient_user, auth_doctor, appointment_factory
):
    """EXISTS, not "the most recent". A patient who cancels one appointment and
    keeps another is still this doctor's patient — the rule must not be read as
    "the latest appointment decides"."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CANCELLED,
    )
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    record = await _read(db, patient_user.id, auth_doctor["user"])

    assert record.user_id == patient_user.id


@pytest.mark.asyncio
async def test_a_doctor_cannot_read_another_clinics_patient_relationship(
    db, patient_user, auth_doctor, other_clinic_doctor, appointment_factory
):
    """The appointment is with clinic B's doctor, so clinic A's doctor has no
    relationship with this patient — the doctor rule is per-DOCTOR, which is
    stricter than per-clinic and must stay that way."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_doctor["user"])


@pytest.mark.asyncio
async def test_a_doctor_does_not_inherit_a_colleagues_patient(
    db, patient_user, auth_doctor, another_doctor, appointment_factory
):
    """Same clinic, different doctor. The stricter "patients I treat" rule is
    the point of the doctor branch; a PENDING allowance must not quietly widen
    it to the whole clinic."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=another_doctor.id,
        status=AppointmentStatus.PENDING,
    )

    with pytest.raises(ForbiddenError):
        await _read(db, patient_user.id, auth_doctor["user"])


def test_the_doctor_status_set_is_the_clinical_one_plus_pending():
    """Pins the relationship between the two rules so they cannot drift.

    The doctor set is the desk's set plus PENDING — nothing else. In
    particular CANCELLED is absent from BOTH, and a status added to the enum
    later joins neither.
    """
    from app.domain.policies.patient_access_policy import (
        CLINICAL_RELATIONSHIP_STATUSES,
        DOCTOR_REVIEW_STATUSES,
    )

    assert DOCTOR_REVIEW_STATUSES == (
        CLINICAL_RELATIONSHIP_STATUSES | {AppointmentStatus.PENDING}
    )

    assert AppointmentStatus.PENDING in DOCTOR_REVIEW_STATUSES
    assert AppointmentStatus.CANCELLED not in DOCTOR_REVIEW_STATUSES
    assert AppointmentStatus.CANCELLED not in CLINICAL_RELATIONSHIP_STATUSES

    # The desk's rule is untouched by the doctor allowance.
    assert AppointmentStatus.PENDING not in CLINICAL_RELATIONSHIP_STATUSES
