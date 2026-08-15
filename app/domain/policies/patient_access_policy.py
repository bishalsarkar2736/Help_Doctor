"""When a clinic may see a patient's clinical record.

Patients are global identities — they carry no clinic_id and may attend several
clinics — so a clinic's claim on a patient has to be derived. It is derived
from appointments, and this module is the single definition of which
appointments count.

WHY A STATUS FILTER AND NOT MERELY "AN APPOINTMENT EXISTS"
Deriving access from the mere existence of an appointment made the check
self-satisfying for the two roles that can create one. A receptionist or admin
may book on behalf of any existing patient with their own clinic's doctor — a
deliberate, necessary feature for a first-time visit — and that booking wrote
the exact row the record read then accepted as proof of a treatment
relationship. The caller authorised their own read, and since user ids are
sequential the targets were enumerable.

THE LINE, AND WHY IT FALLS HERE
A booking is a request; it becomes a clinical relationship when someone other
than the booking clerk acts on it. In this application exactly two things move
an appointment out of PENDING: the treating doctor confirming it, or the
patient paying for it (payment_service confirms on success). Both are acts by
another party, and neither is available to a receptionist or admin. So the
qualifying set is "everything reachable only after CONFIRMED" — which is a
property of the FSM rather than a hand-picked list.

CANCELLED is excluded even though reaching it may have involved a doctor. A
visit that was called off is not treatment, and leaving it in would let the
escalation survive its own cleanup: book, read, cancel, keep the access.

NO_SHOW is included: it is reachable only from CONFIRMED or WAITING, so a
doctor had already confirmed, and following up on a missed appointment is
ordinary front-desk work.

An allowlist rather than a denylist, so a status added to the enum later grants
nothing until someone decides it should.
"""

from sqlalchemy import exists

from app.models.appointment import Appointment, AppointmentStatus

#: Appointment states that constitute a clinical relationship with the clinic
#: holding the appointment. Every member is unreachable without a doctor's
#: confirmation (or a patient's payment); PENDING and CANCELLED are excluded.
CLINICAL_RELATIONSHIP_STATUSES = frozenset(
    {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.WAITING,
        AppointmentStatus.IN_CONSULTATION,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    }
)

#: Sorted for a stable, readable SQL IN clause across runs.
_QUALIFYING = tuple(sorted(CLINICAL_RELATIONSHIP_STATUSES, key=lambda s: s.value))


def clinical_relationship_exists(patient_ref, clinic_id):
    """An EXISTS predicate: has `patient_ref` been treated at `clinic_id`?

    `patient_ref` is either a literal user id or a column to correlate against
    (``Patient.user_id``), which is what lets the record read, the search and
    the history timeline share one rule instead of drifting into three.

    Returns a predicate rather than a boolean so callers can either select it
    directly or embed it in a larger WHERE clause.
    """
    return exists().where(
        Appointment.patient_id == patient_ref,
        Appointment.clinic_id == clinic_id,
        Appointment.status.in_(_QUALIFYING),
    )


#: The same rule for a DOCTOR, plus PENDING.
#:
#: The desk's rule excludes PENDING because a receptionist creates PENDING rows
#: — they would be authorising their own read. A doctor cannot: booking on
#: behalf is RECEPTIONIST/ADMIN only, so a doctor never manufactures their own
#: access, and the reason for excluding PENDING does not apply to them.
#:
#: What a doctor gains is the normal order of work: reviewing a chart before
#: deciding whether to confirm. Requiring CONFIRMED first would invert it,
#: making a clinician commit to an appointment before being allowed to see who
#: it is for.
#:
#: CANCELLED stays excluded here too. A visit that was called off is not
#: treatment, and one cancelled appointment must not leave a doctor with
#: permanent access to that patient's record. It also bounds the indirect path:
#: reception can put any patient in front of a doctor by booking them, and this
#: keeps that exposure lasting only as long as the appointment does.
DOCTOR_REVIEW_STATUSES = CLINICAL_RELATIONSHIP_STATUSES | {
    AppointmentStatus.PENDING
}

_DOCTOR_QUALIFYING = tuple(
    sorted(DOCTOR_REVIEW_STATUSES, key=lambda s: s.value)
)


def doctor_relationship_exists(doctor_id, patient_ref):
    """An EXISTS predicate: does this DOCTOR treat `patient_ref`?

    Scoped to the doctor rather than the clinic — stricter than the rule the
    front desk gets, and deliberately so: a doctor sees the patients they
    treat, not every patient of their clinic. The clinic bound comes for free,
    since a doctor_id belongs to exactly one clinic.
    """
    return exists().where(
        Appointment.doctor_id == doctor_id,
        Appointment.patient_id == patient_ref,
        Appointment.status.in_(_DOCTOR_QUALIFYING),
    )
