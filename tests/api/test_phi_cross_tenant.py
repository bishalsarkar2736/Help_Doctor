"""Tenant isolation for PHI and for the PHI access log itself.

Two distinct questions, and both matter:

1. Can clinic A's staff READ clinic B's patient data?
2. Can clinic A's admin read the ACCESS LOG of clinic B?

The second is easy to overlook. An access log is metadata about patients — who
was treated where, by whom, and when — so leaking it across tenants is itself a
disclosure, even though it contains no diagnoses.

Every test here pairs a denial with the corresponding allowed case, so a
regression that breaks the feature outright cannot masquerade as good security.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import UTC
from app.models.appointment import Appointment, AppointmentStatus
from app.models.phi_access_log import PHIAccessLog, PHIResourceType
from tests.conftest import valid_slot


# ---------------------------------------------------------------------------
# 1. Cross-tenant PHI reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doctor_cannot_read_a_patient_from_another_clinic(
    client, other_clinic_patient, auth_doctor
):
    """Clinic A's doctor has no treatment relationship with clinic B's patient."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_doctor["headers"]
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_the_other_clinics_own_doctor_can_read_them(
    client, other_clinic_patient, other_clinic_doctor
):
    """The paired allow-case: denial above is isolation, not a broken endpoint."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == other_clinic_patient.id


@pytest.mark.asyncio
async def test_admin_cannot_read_another_clinics_patient_history(
    client, other_clinic_patient, auth_admin, second_clinic
):
    """Even naming clinic B explicitly must not grant clinic A's admin access."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}/history",
        params={"clinic_id": second_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_cross_tenant_denial_writes_no_phi_access_row(
    client, db, other_clinic_patient, auth_doctor
):
    """A refused read is not an access and must not be recorded as one.

    Logging denials here would put clinic B's patient ids into rows tagged with
    clinic A — the log would itself become a cross-tenant leak.
    """

    await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_doctor["headers"]
    )

    rows = (
        await db.scalars(
            select(PHIAccessLog).where(
                PHIAccessLog.patient_id == other_clinic_patient.id,
                PHIAccessLog.actor_user_id == auth_doctor["user"].id,
            )
        )
    ).all()
    assert rows == [], "a denied read was recorded as a PHI access"


@pytest.mark.asyncio
async def test_access_is_recorded_against_the_clinic_it_happened_in(
    client, db, other_clinic_patient, other_clinic_doctor, second_clinic
):
    res = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )
    assert res.status_code == 200

    log = await db.scalar(
        select(PHIAccessLog)
        .where(PHIAccessLog.patient_id == other_clinic_patient.id)
        .order_by(PHIAccessLog.id.desc())
    )
    assert log is not None
    assert log.clinic_id == second_clinic.id, (
        "access was attributed to the wrong clinic, which would hide it from "
        "the owning clinic's review and expose it to another's"
    )


# ---------------------------------------------------------------------------
# 2. Cross-tenant reads of the access log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_query_another_clinics_access_log(
    client, other_clinic_patient, other_clinic_doctor, auth_admin, second_clinic
):
    # Generate a real access inside clinic B first.
    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    # Clinic A's admin asks for clinic B's log by id.
    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": second_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_admin_querying_their_own_clinic_sees_only_their_own_rows(
    client,
    db,
    other_clinic_patient,
    other_clinic_doctor,
    auth_admin,
    auth_doctor,
    patient_user,
    default_clinic,
    appointment_factory,
):
    """The filter must be the resolved clinic, not one the caller supplies."""

    # An access in clinic B...
    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    # ...and one in clinic A.
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )
    await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()["items"]
    assert all(r["clinic_id"] == default_clinic.id for r in body)
    assert all(r["patient_id"] != other_clinic_patient.id for r in body), (
        "clinic B's patient appeared in clinic A's access log"
    )


@pytest.mark.asyncio
async def test_filtering_by_another_clinics_patient_returns_nothing(
    client, other_clinic_patient, other_clinic_doctor, auth_admin, default_clinic
):
    """Naming a foreign patient id must not bypass the clinic scope."""

    await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=other_clinic_doctor["headers"],
    )

    res = await client.get(
        "/admin/phi-access",
        params={
            "clinic_id": default_clinic.id,
            "patient_id": other_clinic_patient.id,
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200
    assert res.json()["items"] == []
    assert res.json()["total_count"] == 0


# ---------------------------------------------------------------------------
# 3. The same read, by the two roles that were never tested on it
#
# test_doctor_cannot_read_a_patient_from_another_clinic at the top of this file
# covers GET /patients/{id} for a DOCTOR, and the handler guards that branch by
# requiring an appointment with that doctor. ADMIN and RECEPTIONIST reach the
# same handler through the same require_roles, and there is no branch for them
# at all: `clinic_id = current_user.clinic_id` is assigned for the log and the
# record is returned.
#
# Counting the whole suite, GET /patients/{id} is called 8 times as auth_doctor,
# 5 as other_clinic_doctor, once as auth_patient, and never as either of the two
# roles that are unguarded.
#
# The response is PatientRead: allergies, current medications, chronic
# conditions, blood type. Patient ids are sequential user ids.
#
# WHAT "OWN CLINIC" MEANS HERE
# Patients are global identities — they carry no clinic_id, and
# test_a_patient_is_not_bound_to_a_clinic pins that. A clinic's relationship to
# a patient is derived from appointments, which is the rule search_patients
# already states: "restricted to patients with at least one appointment at
# clinic_id". The allow-cases below therefore give clinic A's patient a real
# appointment at clinic A, so they keep passing under that rule rather than
# only under today's absent one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_read_another_clinics_patient_record(
    client, other_clinic_patient, auth_admin
):
    """The admin twin of the doctor test at the top of this file."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_admin["headers"]
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_receptionist_cannot_read_another_clinics_patient_record(
    client, other_clinic_patient, auth_receptionist
):
    """Same handler, same gap, and typically the least-trusted staff account."""

    res = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=auth_receptionist["headers"],
    )

    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_no_clinical_detail_leaks_in_the_refused_response(
    client, other_clinic_patient, auth_admin
):
    """Asserted on the body, not only the status code.

    other_clinic_patient is created with allergies="Penicillin". A status code
    can be corrected while the payload still ships, so this checks the bytes.
    """

    res = await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_admin["headers"]
    )

    assert "Penicillin" not in res.text
    assert "allergies" not in res.text


@pytest.mark.asyncio
async def test_an_admin_can_read_a_patient_of_their_own_clinic(
    client, auth_admin, auth_doctor, patient_user, appointment_factory
):
    """The paired allow-case. Without it, denying every admin would pass."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_admin["headers"]
    )

    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == patient_user.id


@pytest.mark.asyncio
async def test_a_receptionist_can_read_a_patient_of_their_own_clinic(
    client, auth_receptionist, auth_doctor, patient_user, appointment_factory
):
    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    res = await client.get(
        f"/patients/{patient_user.id}", headers=auth_receptionist["headers"]
    )

    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == patient_user.id


@pytest.mark.asyncio
async def test_a_cross_tenant_read_is_not_logged_against_the_readers_clinic(
    client, db, other_clinic_patient, auth_admin, default_clinic
):
    """The audit trail must not record clinic B's patient under clinic A.

    log_phi_access is called with clinic_id=current_user.clinic_id, so today
    this read is attributed to the READER's clinic. That is the inverse of what
    test_access_is_recorded_against_the_clinic_it_happened_in guarantees for the
    doctor path, and it means the owning clinic cannot see the access in their
    own log while another clinic's log gains a patient id belonging to them.
    """

    await client.get(
        f"/patients/{other_clinic_patient.id}", headers=auth_admin["headers"]
    )

    rows = (
        await db.scalars(
            select(PHIAccessLog).where(
                PHIAccessLog.patient_id == other_clinic_patient.id,
                PHIAccessLog.clinic_id == default_clinic.id,
            )
        )
    ).all()

    assert rows == [], (
        "clinic B's patient was written into clinic A's PHI access log"
    )


# ---------------------------------------------------------------------------
# 4. Selecting a patient is not reading their record
#
# The two halves of this are each well covered — 29 tests for the search
# scoping and its first-booking exception, and the record-read tests above —
# but nothing asserted them TOGETHER, and together is where the product rule
# lives:
#
#     Rahim calls clinic A. Reception verifies who he is, finds him by the
#     phone number he just gave them, and books him with Doctor A. Reception
#     must be able to do all of that WITHOUT his medical record.
#
# search_patients lets a caller holding a full email or phone reach a patient
# outside their clinic — the identifier is the authorisation, and without it
# reception deadlocks, since a patient becomes findable by being booked and is
# booked by first being found. The risk that opens is the assumption that
# "I can see them in search" means "I may open their chart".
#
# These two tests pin the composition, so the rule survives someone widening
# PatientSearchOut for a booking screen, or relaxing the record read because
# reception can already see the patient in the list.
# ---------------------------------------------------------------------------


#: Every clinical field on PatientRead, plus the value other_clinic_patient is
#: actually created with. Checked against the raw response bytes rather than
#: parsed keys, since a nested or renamed field would still be a disclosure.
CLINICAL_FIELDS = (
    "allergies",
    "current_medications",
    "chronic_conditions",
    "blood_type",
    "emergency_contact_name",
    "emergency_contact_phone",
    "date_of_birth",
    "Penicillin",
)


@pytest.mark.asyncio
async def test_finding_a_patient_by_identifier_does_not_expose_their_record(
    client, auth_receptionist, other_clinic_patient
):
    """Reception may confirm the person on the phone. That is all."""

    # The exact phone Rahim just read out. He has never been to this clinic.
    search = await client.get(
        "/patients/search",
        params={"q": "01900000000"},
        headers=auth_receptionist["headers"],
    )
    assert search.status_code == 200, search.text

    results = search.json()

    assert any(row["user_id"] == other_clinic_patient.id for row in results), (
        "the first-booking exception did not surface the patient, so reception "
        "cannot book someone who has never attended — the deadlock this "
        "exception exists to break"
    )

    # Enough to identify and book: who they are, and how to reach them.
    row = next(r for r in results if r["user_id"] == other_clinic_patient.id)
    assert {"id", "user_id", "full_name", "email", "phone"} >= set(row)

    for field in CLINICAL_FIELDS:
        assert field not in search.text, (
            f"{field!r} appeared in a patient SELECTION response"
        )

    # And the record itself stays shut: findable is not readable.
    record = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=auth_receptionist["headers"],
    )
    assert record.status_code in (403, 404), record.text

    for field in CLINICAL_FIELDS:
        assert field not in record.text


@pytest.mark.asyncio
async def test_confirming_the_booking_is_what_opens_their_record(
    client, db, auth_receptionist, other_clinic_patient, doctor, doctor_availability
):
    """The paired allow-case, and the rest of Rahim's call.

    THIS TEST CHANGED. It previously asserted that the BOOKING alone opened the
    chart, which is the same act as the escalation: reception may book any
    existing patient with their own clinic's doctor, so "an appointment exists"
    was a fact the reader could create for themselves, and user ids are
    sequential. The desk could walk the id space and read every chart on the
    platform.

    The relationship is still what decides — that part was always right — but
    it now begins when someone other than the booking clerk has acted on the
    appointment. Reception books Rahim, the doctor confirms him, and then the
    desk that will receive him can see the chart.

    Nothing is lost from the workflow: an appointment cannot progress at all
    without confirmation (the FSM reaches CHECKED_IN only from CONFIRMED, and
    confirm is doctor-only), so the step this now waits for is one that has to
    happen anyway.

    The confirmation is applied directly rather than through the doctor's
    endpoint to keep this test about the authorisation boundary, not about the
    confirm route's own preconditions, which have their own tests.
    """

    slot = valid_slot(datetime.now(UTC) + timedelta(days=1))

    booking = await client.post(
        "/appointments/",
        json={
            "doctor_id": doctor.id,
            "scheduled_at": slot.isoformat(),
            "patient_id": other_clinic_patient.id,
        },
        headers=auth_receptionist["headers"],
    )
    assert booking.status_code == 200, booking.text

    # Booking alone is not yet a clinical relationship.
    too_early = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=auth_receptionist["headers"],
    )
    assert too_early.status_code in (403, 404), too_early.text

    for field in CLINICAL_FIELDS:
        assert field not in too_early.text

    appointment = await db.get(
        Appointment, booking.json()["appointment_id"]
    )
    appointment.status = AppointmentStatus.CONFIRMED
    # chk_confirmed_requires_timestamp: the database refuses a CONFIRMED row
    # with no confirmed_at, and the auto-stamping listener runs on insert, not
    # on this update. A real confirmation sets both.
    appointment.confirmed_at = datetime.now(UTC)
    await db.flush()

    record = await client.get(
        f"/patients/{other_clinic_patient.id}",
        headers=auth_receptionist["headers"],
    )
    assert record.status_code == 200, record.text
    assert record.json()["user_id"] == other_clinic_patient.id


@pytest.mark.asyncio
async def test_non_admin_roles_cannot_read_the_access_log(
    client, auth_doctor, auth_patient, default_clinic
):
    for headers in (auth_doctor["headers"], auth_patient["headers"]):
        res = await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id},
            headers=headers,
        )
        assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_the_access_log_is_reachable_at_all(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic,
    appointment_factory,
):
    """Paired allow-case for the denials above."""

    await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )
    await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()["items"]
    assert body, "no rows returned despite a recorded access"
    assert body[0]["resource_type"] == PHIResourceType.PATIENT_PROFILE
