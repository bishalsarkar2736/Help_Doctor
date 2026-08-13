import pytest
import pytest_asyncio
from datetime import datetime

from sqlalchemy import select

from app.core.time import UTC
from app.models.clinic import Clinic
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.appointment import Appointment
from app.models.prescription import Prescription
from app.services.appointment_service import (
    get_appointment_by_id,
)
from app.services.prescription_service import (
    get_appointment_prescription,
    get_prescription_by_id,
)
from app.try_except.exceptions import (
    ForbiddenError,
    NotFoundError,
)


@pytest.mark.asyncio
async def test_doctor_cannot_access_other_clinic_appointment(
    db,
):
    # -------------------------
    # Clinic A
    # -------------------------
    clinic_a = Clinic(
        name="Clinic A",
    )

    # -------------------------
    # Clinic B
    # -------------------------
    clinic_b = Clinic(
        name="Clinic B",
    )

    db.add_all([clinic_a, clinic_b])
    await db.flush()

    # -------------------------
    # Doctor A
    # -------------------------
    doctor_user_a = User(
        email="doctora@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    # -------------------------
    # Doctor B
    # -------------------------
    doctor_user_b = User(
        email="doctorb@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    # Patient
    patient_user = User(
        email="patient@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    db.add_all(
        [
            doctor_user_a,
            doctor_user_b,
            patient_user,
        ]
    )
    await db.flush()

    doctor_a = Doctor(
        user_id=doctor_user_a.id,
        clinic_id=clinic_a.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor A",
        status=DoctorStatus.APPROVED,
    )

    doctor_b = Doctor(
        user_id=doctor_user_b.id,
        clinic_id=clinic_b.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor B",
        status=DoctorStatus.APPROVED,
    )

    db.add_all([doctor_a, doctor_b])
    await db.flush()

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor_a.id,
        clinic_id=clinic_a.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.commit()

    with pytest.raises(
        ForbiddenError,
        match="Cross-clinic access denied",
    ):
        await get_appointment_by_id(
            db=db,
            appointment_id=appointment.id,
            user=doctor_user_b,
        )


@pytest.mark.asyncio
async def test_doctor_cannot_access_other_clinic_prescription(
    db,
):
    # -------------------------
    # Clinics
    # -------------------------
    clinic_a = Clinic(
        name="Clinic A",
    )

    clinic_b = Clinic(
        name="Clinic B",
    )

    db.add_all([clinic_a, clinic_b])
    await db.flush()

    # -------------------------
    # Users
    # -------------------------
    doctor_user_a = User(
        email="doctora2@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    doctor_user_b = User(
        email="doctorb2@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    patient_user = User(
        email="patient2@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    db.add_all(
        [
            doctor_user_a,
            doctor_user_b,
            patient_user,
        ]
    )

    await db.flush()

    doctor_a = Doctor(
        user_id=doctor_user_a.id,
        clinic_id=clinic_a.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor A",
        status=DoctorStatus.APPROVED,
    )

    doctor_b = Doctor(
        user_id=doctor_user_b.id,
        clinic_id=clinic_b.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor B",
        status=DoctorStatus.APPROVED,
    )

    db.add_all([doctor_a, doctor_b])
    await db.flush()

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor_a.id,
        clinic_id=clinic_a.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.flush()

    prescription = Prescription(
        appointment_id=appointment.id,
        doctor_id=doctor_a.id,
        patient_id=patient_user.id,
        clinic_id=clinic_a.id,
    )

    db.add(prescription)

    await db.commit()

    with pytest.raises(
        ForbiddenError,
        match="Cross-clinic access denied",
    ):
        await get_prescription_by_id(
            db=db,
            prescription_id=prescription.id,
            user=doctor_user_b,
        )


# ---------------------------------------------------------------------------
# ADMIN — the role both checks above forgot
#
# The two tests at the top of this file both prove the boundary by moving a
# DOCTOR between clinics, and so does every other cross-clinic test in this
# suite. That is the blind spot: in prescription_service every role branch is
# guarded except ADMIN, which either falls through with `pass` or runs a query
# with the clinic predicate simply missing.
#
# ADMIN is a clinic-bound role here, not a platform one — resolve_clinic_id
# raises "Admin not assigned to clinic" without a clinic_id, and the platform
# plane is SUPER_ADMIN. So an admin reading another clinic's prescription is a
# tenant breach, and the data is PHI: items carry medicine and dosage.
#
# These use the conftest tenant-B fixtures rather than building clinics inline
# like the tests above, because those fixtures exist for exactly this and give
# clinic B a patient with a real treatment relationship.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def other_clinic_prescription(
    db,
    second_clinic,
    other_clinic_doctor,
    other_clinic_patient,
):
    """A prescription that belongs to clinic B, written by clinic B's doctor.

    Hangs off the appointment `other_clinic_patient` already creates, so the
    row is reachable both by its own id and by its appointment id — the two
    routes the tests below attack.
    """

    appointment = await db.scalar(
        select(Appointment).where(
            Appointment.patient_id == other_clinic_patient.id,
            Appointment.clinic_id == second_clinic.id,
        )
    )

    assert appointment is not None, "fixture setup: clinic B has no appointment"

    prescription = Prescription(
        appointment_id=appointment.id,
        doctor_id=other_clinic_doctor["doctor"].id,
        patient_id=other_clinic_patient.id,
        clinic_id=second_clinic.id,
    )

    db.add(prescription)
    await db.flush()
    await db.refresh(prescription)

    return prescription


@pytest.mark.asyncio
async def test_admin_cannot_read_another_clinics_prescription(
    db,
    auth_admin,
    other_clinic_prescription,
):
    """get_prescription_by_id: the ADMIN branch is `pass`.

    Either denial is acceptable — ForbiddenError to match the doctor branch's
    "Cross-clinic access denied", or NotFoundError to avoid confirming that the
    id exists. What is not acceptable is returning the row.
    """

    with pytest.raises((ForbiddenError, NotFoundError)):
        await get_prescription_by_id(
            db=db,
            prescription_id=other_clinic_prescription.id,
            user=auth_admin["user"],
        )


@pytest.mark.asyncio
async def test_the_other_clinics_own_admin_can_read_its_prescription(
    db,
    other_clinic_admin,
    other_clinic_prescription,
):
    """The paired allow-case: the denial above must be isolation, not a
    prescription lookup that stopped working for admins entirely."""

    prescription = await get_prescription_by_id(
        db=db,
        prescription_id=other_clinic_prescription.id,
        user=other_clinic_admin["user"],
    )

    assert prescription.id == other_clinic_prescription.id


@pytest.mark.asyncio
async def test_admin_cannot_read_another_clinics_prescription_by_appointment(
    db,
    auth_admin,
    other_clinic_prescription,
):
    """get_appointment_prescription: the second, better-hidden version.

    Here the ADMIN branch is not a missing check but a differently-filtered
    query — it selects on appointment_id alone, while the doctor branch also
    filters doctor_id and clinic_id. Same breach, no `pass` to grep for.
    """

    with pytest.raises((ForbiddenError, NotFoundError)):
        await get_appointment_prescription(
            db=db,
            appointment_id=other_clinic_prescription.appointment_id,
            user=auth_admin["user"],
        )


@pytest.mark.asyncio
async def test_the_other_clinics_own_admin_can_read_it_by_appointment(
    db,
    other_clinic_admin,
    other_clinic_prescription,
):
    prescription = await get_appointment_prescription(
        db=db,
        appointment_id=other_clinic_prescription.appointment_id,
        user=other_clinic_admin["user"],
    )

    assert prescription.id == other_clinic_prescription.id