"""The one place a prescription is checked against a patient's allergies.

Every path that decides what medicines a patient will take goes through here:
creating, editing a draft, issuing a revision, and issuing. Previously only
creation checked anything, so a doctor could create a clean draft, edit an
allergen into it, and issue it with no warning and nothing in the audit trail.

The check and the audit record are produced by the SAME function on purpose.
Splitting them is how the old code drifted: three call sites wrote items, one
of them remembered to check, and nothing made that visible.

WHAT COUNTS AS A NEW CONFLICT
-----------------------------
A prescriber who has already justified an override should not be asked again
every time they adjust a dosage. So a conflict already covered by the stored
justification passes without a fresh reason.

"Already covered" is compared on the resolved SUBSTANCE, not the typed name.
Renaming a line from "Cefim" to "Cefim 400mg", or swapping to a sibling brand
of the same generic, is not a new clinical decision — but comparing typed
strings would treat it as one and demand a fresh justification for a judgement
that has not changed.

The comparison runs against the patient's allergies AS THEY ARE NOW. An allergy
recorded after the draft was written makes its medicine a new conflict even
though nothing about the prescription changed, which is exactly the case the
check exists for.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.prescribing.allergy import find_allergy_conflicts
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.services.medicine_lookup_service import (
    resolve_generics_for_items,
    resolve_substance_aliases,
    verify_medicine_ids,
)
from app.try_except.audit import log_audit_event
from app.try_except.exceptions import BadRequestError

# Shortest acceptable justification for prescribing through an allergy warning.
# Long enough to exclude "ok" / "x" / "n/a" — a trail full of those is no better
# than no reason at all — while staying short enough not to obstruct a
# prescriber acting in an emergency.
MIN_ALLERGY_OVERRIDE_REASON = 10


class _Prescribed:
    """A medicine to be checked, from a request item or a template row."""

    __slots__ = ("medicine_name", "medicine_id")

    def __init__(self, medicine_name: str, medicine_id: int | None = None):
        self.medicine_name = medicine_name
        self.medicine_id = medicine_id


def describe_conflict(name: str, generic_names: dict[str, str]) -> str:
    """Name a flagged medicine, and the substance it was flagged for.

    "Cefim" tells a prescriber which line to look at but not why it fired —
    the patient is not allergic to Cefim, they are allergic to the Cefixime in
    it. Naming both is the difference between a warning that can be judged and
    one that gets overridden to make it go away.
    """
    generic = generic_names.get(name)

    if generic and generic.lower() != name.lower():
        return f"{name} ({generic})"

    return name


async def load_patient_for_prescription(
    db: AsyncSession,
    patient_user_id: int,
) -> Patient | None:
    """Resolve the patient record from a USER id.

    prescriptions.patient_id and appointments.patient_id are both FKs to
    users.id, so the patient row is found through Patient.user_id. Matching on
    Patient.id instead finds the wrong person or nobody — and nobody means no
    allergies, which means the check silently passes everything. It would look
    like it was working.
    """
    return await db.scalar(
        select(Patient).where(Patient.user_id == patient_user_id)
    )


def _substances(names: list[str], generic_names: dict[str, str]) -> set[str]:
    """The active substances behind a set of flagged medicines.

    Falls back to the typed name where nothing resolved, so a free-text
    medicine still contributes something stable to compare against.
    """
    return {(generic_names.get(name) or name).strip().lower() for name in names}


async def validate_prescription_allergies(
    *,
    db: AsyncSession,
    patient_user_id: int,
    items,
    template_items=None,
    override: bool = False,
    override_reason: str | None = None,
    previously_justified: list[str] | None = None,
    actor_user_id: int | None = None,
    prescription: Prescription | None = None,
    audit: bool = True,
) -> tuple[list[str], dict[str, str], str]:
    """Check what is about to be prescribed, and record any override.

    `items` are request items (they may carry a selected medicine_id);
    `template_items` are rows pulled from a prescription template, which have a
    name only. Both end up on the prescription, so both are checked — template
    medicines were previously added AFTER the check and never examined at all.

    `previously_justified` are the substances an earlier override on this
    prescription already covered. Conflicts inside that set do not require a
    fresh reason; anything outside it does.

    Returns the flagged medicine names, the resolved substances, and the reason
    that should be stored on the prescription.
    """
    prescribed = [
        _Prescribed(item.medicine_name, getattr(item, "medicine_id", None))
        for item in items
    ]

    prescribed += [
        _Prescribed(item.medicine_name, getattr(item, "medicine_id", None))
        for item in (template_items or [])
    ]

    # A selected catalogue id must actually exist. Silently dropping an unknown
    # one would store a prescription whose allergy check ran on the typed name
    # while the request claimed a catalogue link.
    await verify_medicine_ids(db, prescribed)

    patient = await load_patient_for_prescription(db, patient_user_id)

    # Resolve each item to its active substance so the check sees what a
    # patient actually reacts to. Without this a patient allergic to "Cefixime"
    # gets no warning when prescribed "Cefim" — one of its eleven brands.
    generic_names = await resolve_generics_for_items(db, prescribed)

    # And the other names those substances go by, so an allergy recorded as
    # "Acetaminophen" is matched against every Paracetamol brand.
    substance_aliases = await resolve_substance_aliases(
        db, list(generic_names.values())
    )

    conflicts = find_allergy_conflicts(
        patient.allergies if patient else None,
        [item.medicine_name for item in prescribed],
        generic_names,
        substance_aliases,
    )

    reason = (override_reason or "").strip()

    if not conflicts:
        # Nothing to justify. Any stored reason is dropped by the caller, so a
        # justification cannot outlive the conflict it was given for.
        return [], generic_names, ""

    covered = {s.strip().lower() for s in (previously_justified or [])}
    unjustified = _substances(conflicts, generic_names) - covered

    if unjustified and not override:
        raise BadRequestError(
            "Patient has a recorded allergy to: "
            + ", ".join(describe_conflict(name, generic_names) for name in conflicts)
            + ". Review, then resubmit with override to proceed."
        )

    # Requiring the reason only for a conflict that is not already justified:
    # a prescriber adjusting a dosage on a prescription they already explained
    # should not have to explain it again, but a newly introduced allergen —
    # or a newly recorded allergy — is a fresh decision.
    if unjustified and len(reason) < MIN_ALLERGY_OVERRIDE_REASON:
        raise BadRequestError(
            "Overriding an allergy warning requires a clinical reason of at "
            f"least {MIN_ALLERGY_OVERRIDE_REASON} characters, recorded in the "
            "audit trail."
        )

    if not unjustified and not reason:
        # Carried forward unchanged: the justification still applies, and the
        # record must not lose it just because this request did not resend it.
        reason = _carry_forward(prescription)

    if audit and unjustified:
        await _audit_override(
            db=db,
            actor_user_id=actor_user_id,
            prescription=prescription,
            patient_user_id=patient_user_id,
            patient=patient,
            conflicts=conflicts,
            generic_names=generic_names,
            reason=reason,
        )

    return conflicts, generic_names, reason


def _carry_forward(prescription: Prescription | None) -> str:
    return (prescription.allergy_override_reason or "") if prescription else ""


async def _audit_override(
    *,
    db: AsyncSession,
    actor_user_id: int | None,
    prescription: Prescription | None,
    patient_user_id: int,
    patient: Patient | None,
    conflicts: list[str],
    generic_names: dict[str, str],
    reason: str,
) -> None:
    """Record the override.

    Written here rather than at each call site so that create, edit, revision
    and issue all produce the same record — the previous code audited overrides
    on creation only, which is also the only path that checked for them.
    """
    await log_audit_event(
        db=db,
        event_type="prescription",
        action="allergy_override",
        user_id=actor_user_id,
        resource="prescription",
        details={
            "prescription_id": prescription.id if prescription else None,
            "patient_id": patient_user_id,
            "conflicts": conflicts,
            "substances": sorted(_substances(conflicts, generic_names)),
            "reason": reason,
            # The allergens as recorded at the time. The patient's allergy list
            # can be edited later; the trail must show what the prescriber was
            # actually warned about.
            "patient_allergies_at_time": patient.allergies if patient else None,
        },
    )


def apply_override_state(
    prescription: Prescription,
    conflicts: list[str],
    generic_names: dict[str, str],
    reason: str,
) -> None:
    """Store the justification on the record it justifies.

    Kept on the prescription, not only in the audit log: the log is an
    append-only trail for investigators and is subject to retention purging,
    so reading it to decide whether a fresh reason is needed would make a
    safety rule depend on log retention. It also means a clinician reading the
    prescription can see why an allergy was overridden at all.
    """
    if conflicts:
        prescription.allergy_override_reason = reason or None
        prescription.allergy_override_substances = sorted(
            _substances(conflicts, generic_names)
        )
    else:
        # No conflict left — drop the justification rather than let it sit on a
        # prescription it no longer describes.
        prescription.allergy_override_reason = None
        prescription.allergy_override_substances = None
