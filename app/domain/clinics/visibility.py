"""Whether a clinic is open to the public right now.

One definition, used by every public path. The bug this exists to prevent is
drift: /clinics filtered on status while /doctors did not, so a suspended
clinic disappeared from the clinic picker and its doctors stayed listed,
bookable, and answerable by the assistant. Repeating the same WHERE clause in
eight places is what manufactures the ninth place that forgets it.

WHAT SUSPENSION MEANS
---------------------
A suspended clinic is temporarily offline. It is hidden from discovery, cannot
be booked, and its staff cannot log in. DELETED behaves identically — the two
differ in reversibility and intent, not in what the public sees, which is why a
single predicate covers both.

WHAT IT DOES NOT MEAN
---------------------
This governs DISCOVERY, never a patient's own records. Appointments,
prescriptions, PDFs and history stay reachable by the patient they belong to: a
clinic suspended over an unpaid invoice is a commercial matter, and withholding
someone's medical history for it would be the wrong answer to the wrong
question.

Prescription verification is likewise untouched. A pharmacist confirming a
document issued while the clinic was active is checking authenticity, not
availability, and suspension does not retroactively invalidate a prescription.
"""

from sqlalchemy import ColumnElement

from app.models.clinic import Clinic, ClinicStatus


def clinic_is_public() -> tuple[ColumnElement[bool], ...]:
    """Conditions a clinic must meet to appear in public listings.

    Returned as a tuple so it can be unpacked straight into a `.where(...)`
    alongside other conditions:

        .where(Doctor.clinic_id == Clinic.id, *clinic_is_public())

    Both halves are checked. status and deleted_at are written by different
    flows, and a row carrying a deletion timestamp is deleted whatever its
    status column says.
    """
    return (
        Clinic.status == ClinicStatus.ACTIVE,
        Clinic.deleted_at.is_(None),
    )


def is_public(clinic: Clinic | None) -> bool:
    """The same rule applied to a clinic already loaded.

    For paths holding the object rather than building a query — booking
    validation, tenant resolution — so neither can disagree with a listing
    about whether the same clinic is open.
    """
    if clinic is None:
        return False

    return clinic.status == ClinicStatus.ACTIVE and clinic.deleted_at is None
