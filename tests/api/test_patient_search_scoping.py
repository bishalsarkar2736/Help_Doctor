"""Patient search sees one clinic's patients.

Patients are global identities on purpose — the same person may be treated at
more than one clinic, and duplicating them per tenant would split their
history. So "belongs to this clinic" is derived rather than stored, and the
relationship that defines it is an appointment.

Before this, search was role-guarded and nothing more: any admin, doctor or
receptionist could find any patient on the platform by name, email or phone.
The audit log recorded it, so trawling was detectable afterwards — nothing
prevented it.

The clinic is taken from the authenticated principal and never from the
request, which is asserted directly: resolve_clinic_id returns the
caller-supplied value unchanged for receptionists, so a search scoped to a
query parameter could be pointed at another tenant by editing a URL.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.patient_search_service import search_patients


async def _clinic(db, name: str) -> Clinic:
    clinic = Clinic(name=name, status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")
    db.add(clinic)
    await db.flush()
    return clinic


async def _patient(db, *, email: str, name: str) -> User:
    user = User(
        email=email,
        full_name=name,
        hashed_password="x",
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        Patient(
            user_id=user.id,
            phone=f"+88017{user.id:08d}",
            address="somewhere",
            date_of_birth=utc_now().date(),
            gender=Gender.MALE,
        )
    )
    await db.flush()
    return user


async def _doctor(db, clinic: Clinic, *, email: str) -> Doctor:
    user = User(
        email=email,
        full_name=f"Dr {email.split('@')[0]}",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=clinic.id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()
    return doctor


async def _staff(db, clinic: Clinic, role: UserRole, email: str) -> dict:
    user = User(
        email=email,
        full_name=f"{role.value} {clinic.name}",
        hashed_password="x",
        role=role,
        is_active=True,
        clinic_id=clinic.id,
    )
    db.add(user)
    await db.flush()

    token = create_access_token(data={"sub": str(user.id), "role": role.value})

    return {"user": user, "headers": {"Authorization": f"Bearer {token}"}}


async def _appointment(db, clinic: Clinic, doctor: Doctor, patient: User, *, hours=2):
    start = utc_now() + timedelta(hours=hours)

    db.add(
        Appointment(
            patient_id=patient.id,
            doctor_id=doctor.id,
            clinic_id=clinic.id,
            scheduled_at=start,
            status=AppointmentStatus.PENDING,
            time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
        )
    )
    await db.flush()


@pytest.fixture
async def two_clinics(db):
    """Two clinics, a patient at each, and one shared between them."""
    alpha = await _clinic(db, "Alpha Clinic")
    beta = await _clinic(db, "Beta Clinic")

    alpha_doctor = await _doctor(db, alpha, email="alpha-doc@example.com")
    beta_doctor = await _doctor(db, beta, email="beta-doc@example.com")

    only_alpha = await _patient(db, email="a@example.com", name="Searchable AlphaOnly")
    only_beta = await _patient(db, email="b@example.com", name="Searchable BetaOnly")
    shared = await _patient(db, email="s@example.com", name="Searchable Shared")
    never_seen = await _patient(db, email="n@example.com", name="Searchable NoBookings")

    await _appointment(db, alpha, alpha_doctor, only_alpha, hours=2)
    await _appointment(db, beta, beta_doctor, only_beta, hours=3)
    await _appointment(db, alpha, alpha_doctor, shared, hours=4)
    await _appointment(db, beta, beta_doctor, shared, hours=5)

    await db.commit()

    return {
        "alpha": alpha,
        "beta": beta,
        "alpha_doctor": alpha_doctor,
        "beta_doctor": beta_doctor,
        "only_alpha": only_alpha,
        "only_beta": only_beta,
        "shared": shared,
        "never_seen": never_seen,
    }


async def _search(db, clinic_id, q="Searchable"):
    return [
        r.full_name
        for r in await search_patients(db=db, clinic_id=clinic_id, q=q)
    ]


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clinic_a_cannot_see_clinic_b_patients(db, two_clinics):
    names = await _search(db, two_clinics["alpha"].id)

    assert "Searchable AlphaOnly" in names
    assert "Searchable BetaOnly" not in names


@pytest.mark.asyncio
async def test_clinic_b_cannot_see_clinic_a_patients(db, two_clinics):
    names = await _search(db, two_clinics["beta"].id)

    assert "Searchable BetaOnly" in names
    assert "Searchable AlphaOnly" not in names


@pytest.mark.asyncio
async def test_a_shared_patient_appears_for_both(db, two_clinics):
    """Global identity, two relationships. Each clinic sees them because each
    has treated them — not because the record was duplicated."""
    assert "Searchable Shared" in await _search(db, two_clinics["alpha"].id)
    assert "Searchable Shared" in await _search(db, two_clinics["beta"].id)


@pytest.mark.asyncio
async def test_a_shared_patient_appears_once_per_clinic(db, two_clinics):
    """Two appointments at Alpha would return them twice under a plain join."""
    await _appointment(
        db,
        two_clinics["alpha"],
        two_clinics["alpha_doctor"],
        two_clinics["shared"],
        hours=9,
    )
    await db.commit()

    names = await _search(db, two_clinics["alpha"].id)

    assert names.count("Searchable Shared") == 1


@pytest.mark.asyncio
async def test_a_patient_with_no_appointments_is_not_returned(db, two_clinics):
    """No relationship with any clinic, so no clinic can find them.

    This is the behaviour change with real consequences — see the module note
    in the report: reception books first appointments from this search.
    """
    for clinic in ("alpha", "beta"):
        assert "Searchable NoBookings" not in await _search(
            db, two_clinics[clinic].id
        )


# ---------------------------------------------------------------------------
# Through the endpoint, per role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role, email",
    [
        (UserRole.RECEPTIONIST, "recep@example.com"),
        (UserRole.ADMIN, "admin@example.com"),
    ],
)
async def test_clinic_staff_cannot_see_another_clinics_patients(
    client, db, two_clinics, role, email
):
    staff = await _staff(db, two_clinics["alpha"], role, email)
    await db.commit()

    res = await client.get(
        "/patients/search",
        params={"q": "Searchable"},
        headers=staff["headers"],
    )

    assert res.status_code == 200, res.text

    names = [r["full_name"] for r in res.json()]

    assert "Searchable AlphaOnly" in names
    assert "Searchable BetaOnly" not in names


@pytest.mark.asyncio
async def test_a_doctor_cannot_see_another_clinics_patients(
    client, db, two_clinics
):
    """The doctor's clinic comes from their profile, not their user row."""
    doctor_user = await db.get(User, two_clinics["alpha_doctor"].user_id)

    token = create_access_token(
        data={"sub": str(doctor_user.id), "role": UserRole.DOCTOR.value}
    )

    res = await client.get(
        "/patients/search",
        params={"q": "Searchable"},
        headers={"Authorization": f"Bearer {token}"},
    )

    names = [r["full_name"] for r in res.json()]

    assert "Searchable AlphaOnly" in names
    assert "Searchable BetaOnly" not in names


@pytest.mark.asyncio
async def test_the_clinic_cannot_be_chosen_by_the_caller(
    client, db, two_clinics
):
    """A query parameter must not move the scope.

    resolve_clinic_id returns the caller-supplied value unchanged for
    receptionists, so a search scoped to a parameter could be pointed at
    another tenant by editing a URL.
    """
    staff = await _staff(
        db, two_clinics["alpha"], UserRole.RECEPTIONIST, "recep2@example.com"
    )
    await db.commit()

    res = await client.get(
        "/patients/search",
        params={"q": "Searchable", "clinic_id": two_clinics["beta"].id},
        headers=staff["headers"],
    )

    names = [r["full_name"] for r in res.json()]

    assert "Searchable BetaOnly" not in names


@pytest.mark.asyncio
async def test_a_patient_still_cannot_search(client, db, two_clinics, auth_patient):
    res = await client.get(
        "/patients/search",
        params={"q": "Searchable"},
        headers=auth_patient["headers"],
    )

    assert res.status_code == 403, res.text


# ---------------------------------------------------------------------------
# No regression in what search does
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_name_still_works(db, two_clinics):
    assert "Searchable AlphaOnly" in await _search(
        db, two_clinics["alpha"].id, q="AlphaOnly"
    )


@pytest.mark.asyncio
async def test_search_by_email_still_works(db, two_clinics):
    assert await _search(db, two_clinics["alpha"].id, q="a@example.com")


@pytest.mark.asyncio
async def test_search_by_phone_still_works(db, two_clinics):
    phone = await db.scalar(
        Patient.__table__.select()
        .with_only_columns(Patient.phone)
        .where(Patient.user_id == two_clinics["only_alpha"].id)
    )

    assert await _search(db, two_clinics["alpha"].id, q=phone)


@pytest.mark.asyncio
async def test_an_empty_query_lists_the_clinics_patients(db, two_clinics):
    """Blank search was allowed before and still is — scoped, now."""
    names = await _search(db, two_clinics["alpha"].id, q="")

    assert "Searchable AlphaOnly" in names
    assert "Searchable BetaOnly" not in names


@pytest.mark.asyncio
async def test_a_patient_without_a_name_does_not_break_the_page(db, two_clinics):
    """users.full_name is nullable; PatientSearchOut.full_name is not.

    One nameless patient anywhere in the results raised a ValidationError and
    took down the whole response, so reception loses the search rather than one
    row. Registration demands a name, so no live row is affected — nothing at
    the database level enforces it.
    """
    nameless = await _patient(db, email="noname@example.com", name=None)

    await _appointment(
        db, two_clinics["alpha"], two_clinics["alpha_doctor"], nameless, hours=11
    )
    await db.commit()

    results = await search_patients(
        db=db, clinic_id=two_clinics["alpha"].id, q="noname@example.com"
    )

    assert len(results) == 1
    assert results[0].full_name == ""

    # The point: the rest of the page still comes back.
    assert "Searchable AlphaOnly" in await _search(db, two_clinics["alpha"].id, q="")


@pytest.mark.asyncio
async def test_pagination_is_preserved(db, two_clinics):
    first = await search_patients(
        db=db, clinic_id=two_clinics["alpha"].id, q="Searchable", limit=1, offset=0
    )
    second = await search_patients(
        db=db, clinic_id=two_clinics["alpha"].id, q="Searchable", limit=1, offset=1
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].user_id != second[0].user_id


@pytest.mark.asyncio
async def test_results_are_ordered_by_name(db, two_clinics):
    names = await _search(db, two_clinics["alpha"].id)

    assert names == sorted(names)


@pytest.mark.asyncio
async def test_the_response_shape_is_unchanged(db, two_clinics):
    """Existing clients read these fields."""
    results = await search_patients(
        db=db, clinic_id=two_clinics["alpha"].id, q="AlphaOnly"
    )

    assert set(results[0].model_dump()) == {
        "id",
        "user_id",
        "full_name",
        "email",
        "phone",
    }


# ---------------------------------------------------------------------------
# The first-booking exception
#
# Scoping alone deadlocks reception: a patient becomes findable by being
# booked, and is booked by first being found. An exact email or phone reaches
# a patient at any clinic, because holding the full identifier is the
# authorisation — you can confirm somebody you were already given, not
# discover anyone.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exact_email_finds_a_patient_with_no_appointments(db, two_clinics):
    """The deadlock this exists to break."""
    names = await _search(db, two_clinics["alpha"].id, q="n@example.com")

    assert names == ["Searchable NoBookings"]


@pytest.mark.asyncio
async def test_an_exact_phone_finds_a_patient_with_no_appointments(db, two_clinics):
    phone = await db.scalar(
        select(Patient.phone).where(
            Patient.user_id == two_clinics["never_seen"].id
        )
    )

    names = await _search(db, two_clinics["alpha"].id, q=phone)

    assert names == ["Searchable NoBookings"]


@pytest.mark.asyncio
async def test_an_exact_email_is_matched_case_insensitively(db, two_clinics):
    """Nothing forces the stored address to be lowercase."""
    assert await _search(db, two_clinics["alpha"].id, q="N@ExAmPlE.CoM")


@pytest.mark.asyncio
async def test_the_exception_returns_only_the_exact_match(db, two_clinics):
    """Not everyone whose address contains the string.

    Every patient here has an @example.com address, so a substring rule would
    hand over all four — the whole platform, one domain at a time.
    """
    results = await search_patients(
        db=db, clinic_id=two_clinics["alpha"].id, q="n@example.com"
    )

    assert len(results) == 1
    assert results[0].user_id == two_clinics["never_seen"].id


@pytest.mark.asyncio
async def test_a_partial_identifier_reaches_nobody_outside_the_clinic(db, two_clinics):
    """Where the line sits: equality opens the door, nothing else does."""
    for partial in (
        "example.com",  # the shared domain
        "@example",
        "b@example.co",  # one character short of Beta's patient
        "+88017",  # the shared phone prefix
        "Searchable",  # the shared name
    ):
        names = await _search(db, two_clinics["alpha"].id, q=partial)

        assert "Searchable BetaOnly" not in names, partial
        assert "Searchable NoBookings" not in names, partial


@pytest.mark.asyncio
async def test_a_prefix_of_a_full_phone_does_not_reach_out(db, two_clinics):
    """One character short of the whole number is not the whole number.

    The prefix may still match Alpha's OWN patients as a substring — that is
    ordinary scoped fuzzy search. What it must not do is reach the patient
    whose number it is a prefix of, who belongs to no clinic.
    """
    phone = await db.scalar(
        select(Patient.phone).where(
            Patient.user_id == two_clinics["never_seen"].id
        )
    )

    names = await _search(db, two_clinics["alpha"].id, q=phone[:-1])

    assert "Searchable NoBookings" not in names

    # And the whole number does reach them, so the test above is about the
    # missing character rather than about the number matching nothing.
    assert "Searchable NoBookings" in await _search(
        db, two_clinics["alpha"].id, q=phone
    )


@pytest.mark.asyncio
async def test_a_shared_phone_reaches_everyone_who_shares_it(db, two_clinics):
    """Email is unique; phone is not, and there is no constraint saying so.

    A household sharing one number is ordinary, so an exact phone lookup can
    return more than one person. This is recorded rather than prevented: the
    alternative is picking one of them arbitrarily, and reception booking the
    wrong sibling is worse than reception being shown both.

    Note this is the ONE case where "exact lookup returns a single patient"
    does not hold. It is not enumeration — everyone returned genuinely has
    that number.
    """
    a = await _patient(db, email="h1@example.com", name="Household One")
    b = await _patient(db, email="h2@example.com", name="Household Two")

    shared_number = "+8801999000111"

    for user in (a, b):
        patient = await db.scalar(
            select(Patient).where(Patient.user_id == user.id)
        )
        patient.phone = shared_number

    await db.commit()

    names = await _search(db, two_clinics["alpha"].id, q=shared_number)

    assert sorted(names) == ["Household One", "Household Two"]


@pytest.mark.asyncio
async def test_after_the_first_appointment_normal_search_finds_them(db, two_clinics):
    """The exception is a way in, not a permanent channel.

    Once reception has booked the walk-in, the patient is one of the clinic's
    own and partial name search reaches them like anybody else.
    """
    assert "Searchable NoBookings" not in await _search(
        db, two_clinics["alpha"].id, q="NoBook"
    )

    await _appointment(
        db,
        two_clinics["alpha"],
        two_clinics["alpha_doctor"],
        two_clinics["never_seen"],
        hours=12,
    )
    await db.commit()

    assert "Searchable NoBookings" in await _search(
        db, two_clinics["alpha"].id, q="NoBook"
    )

    # And still only to the clinic that booked them.
    assert "Searchable NoBookings" not in await _search(
        db, two_clinics["beta"].id, q="NoBook"
    )


@pytest.mark.asyncio
async def test_the_exception_does_not_widen_a_partial_search_page(db, two_clinics):
    """A fuzzy search returns the same rows it did before the exception."""
    assert sorted(await _search(db, two_clinics["alpha"].id)) == [
        "Searchable AlphaOnly",
        "Searchable Shared",
    ]


@pytest.mark.asyncio
async def test_the_exception_is_available_through_the_endpoint(
    client, db, two_clinics
):
    """Reception's actual path, not just the service."""
    staff = await _staff(
        db, two_clinics["alpha"], UserRole.RECEPTIONIST, "recep4@example.com"
    )
    await db.commit()

    res = await client.get(
        "/patients/search",
        params={"q": "n@example.com"},
        headers=staff["headers"],
    )

    assert res.status_code == 200, res.text
    assert [r["full_name"] for r in res.json()] == ["Searchable NoBookings"]


@pytest.mark.asyncio
async def test_an_exact_lookup_is_recorded_in_the_phi_log(client, db, two_clinics):
    """The exception reaches outside the clinic, so the trail matters more."""
    from sqlalchemy import func as sa_func

    from app.models.phi_access_log import PHIAccessLog

    staff = await _staff(
        db, two_clinics["alpha"], UserRole.RECEPTIONIST, "recep5@example.com"
    )
    await db.commit()

    before = await db.scalar(select(sa_func.count(PHIAccessLog.id)))

    await client.get(
        "/patients/search",
        params={"q": "n@example.com"},
        headers=staff["headers"],
    )

    rows = await db.scalar(select(sa_func.count(PHIAccessLog.id)))

    assert rows == before + 1


# ---------------------------------------------------------------------------
# The audit trail is untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_surfaced_patients_are_still_logged(client, db, two_clinics):
    """Scoping reduces who can be found; it does not replace recording it."""
    from sqlalchemy import func, select

    from app.models.phi_access_log import PHIAccessLog

    staff = await _staff(
        db, two_clinics["alpha"], UserRole.RECEPTIONIST, "recep3@example.com"
    )
    await db.commit()

    before = await db.scalar(select(func.count(PHIAccessLog.id)))

    await client.get(
        "/patients/search",
        params={"q": "Searchable"},
        headers=staff["headers"],
    )

    assert await db.scalar(select(func.count(PHIAccessLog.id))) > before
