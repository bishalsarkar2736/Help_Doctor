"""Allergy checking on every path that decides what a patient takes.

Creating a prescription was the only path that checked anything. A doctor could
create a clean draft, edit an allergen into it, and issue it — no warning, and
nothing in the audit trail. Revisions were unchecked too, and medicines pulled
from a template were added after the check had already run.

The first test here is the important one. `prescriptions.patient_id` is a FK to
`users.id`, so the patient record is found through `Patient.user_id`. Resolve it
any other way and the lookup returns nobody, nobody has no allergies, and the
check passes everything while appearing to work. It fails open and silently, so
it is asserted identically across all four paths rather than only where the
original code happened to get it right.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.audit_log import AuditLog
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.patient import Patient
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.prescription_template import (
    PrescriptionTemplate,
    PrescriptionTemplateItem,
)

ALLERGEN = "Penicillin"
REASON = "Reaction was a mild rash; benefit outweighs the risk here."


async def _record_allergy(db, patient_user, allergen):
    patient = await db.scalar(
        select(Patient).where(Patient.user_id == patient_user.id)
    )
    if patient is None:
        patient = Patient(user_id=patient_user.id)
        db.add(patient)

    patient.allergies = allergen
    await db.commit()


@pytest.fixture
async def consultation(db, auth_doctor, patient_user, appointment_factory):
    return await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.IN_CONSULTATION,
    )


@pytest.fixture
async def cefim(db):
    """A brand whose name shares no letters with its substance."""
    generic = Generic(name="Cefixime", normalized_name="cefixime")
    db.add(generic)
    await db.flush()

    medicine = Medicine(
        name="Cefim",
        generic_name="Cefixime",
        generic_id=generic.id,
        strength="400mg",
        manufacturer="Square",
        is_brand=True,
    )
    db.add(medicine)
    await db.commit()
    return medicine


def _items(*names):
    return [{"medicine_name": n} for n in names]


async def _create(client, auth, appointment, items, **extra):
    return await client.post(
        f"/prescriptions/appointments/{appointment.id}",
        json={"notes": "n", "items": items, **extra},
        headers=auth["headers"],
    )


async def _update(client, auth, prescription_id, items, **extra):
    return await client.patch(
        f"/prescriptions/{prescription_id}",
        json={"notes": "n", "items": items, **extra},
        headers=auth["headers"],
    )


async def _issue(client, auth, prescription_id):
    return await client.post(
        f"/prescriptions/{prescription_id}/issue",
        headers=auth["headers"],
    )


async def _latest_override(db):
    return await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.event_type == "prescription",
            AuditLog.action == "allergy_override",
        )
        .order_by(AuditLog.id.desc())
    )


# ---------------------------------------------------------------------------
# The patient must be resolved identically everywhere
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_blocks_a_recorded_allergen(
    client, db, auth_doctor, patient_user, consultation
):
    await _record_allergy(db, patient_user, ALLERGEN)

    res = await _create(client, auth_doctor, consultation, _items("Penicillin V"))

    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_edit_blocks_an_allergen_added_after_creation(
    client, db, auth_doctor, patient_user, consultation
):
    """The gap: a clean draft edited into a dangerous one."""
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(client, auth_doctor, consultation, _items("Paracetamol"))
    assert created.status_code in (200, 201), created.text

    res = await _update(
        client, auth_doctor, created.json()["id"], _items("Penicillin V")
    )

    assert res.status_code == 400, res.text
    assert "penicillin" in res.text.lower()


@pytest.mark.asyncio
async def test_edit_blocks_when_the_allergy_is_recorded_afterwards(
    client, db, auth_doctor, patient_user, consultation
):
    """The medicine list never changed — the patient's allergies did.

    Diffing against "did a conflict exist before" would miss this entirely.
    """
    created = await _create(client, auth_doctor, consultation, _items("Penicillin V"))
    assert created.status_code in (200, 201), created.text

    await _record_allergy(db, patient_user, ALLERGEN)

    res = await _update(
        client, auth_doctor, created.json()["id"], _items("Penicillin V")
    )

    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_issue_blocks_an_allergy_recorded_after_the_draft(
    client, db, auth_doctor, patient_user, consultation
):
    created = await _create(client, auth_doctor, consultation, _items("Penicillin V"))
    prescription_id = created.json()["id"]

    await _record_allergy(db, patient_user, ALLERGEN)

    res = await _issue(client, auth_doctor, prescription_id)

    assert res.status_code == 400, res.text
    assert "edit the draft" in res.text.lower()


# ---------------------------------------------------------------------------
# Overriding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_with_an_override_is_allowed_and_audited(
    client, db, auth_doctor, patient_user, consultation
):
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(client, auth_doctor, consultation, _items("Paracetamol"))

    res = await _update(
        client,
        auth_doctor,
        created.json()["id"],
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    assert res.status_code in (200, 201), res.text

    record = await _latest_override(db)
    assert record is not None
    assert record.details["reason"] == REASON
    assert record.details["patient_allergies_at_time"] == ALLERGEN


@pytest.mark.asyncio
async def test_edit_override_without_a_reason_is_refused(
    client, db, auth_doctor, patient_user, consultation
):
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(client, auth_doctor, consultation, _items("Paracetamol"))

    res = await _update(
        client,
        auth_doctor,
        created.json()["id"],
        _items("Penicillin V"),
        allergy_override=True,
    )

    assert res.status_code == 400, res.text
    assert "reason" in res.text.lower()


@pytest.mark.asyncio
async def test_a_dosage_only_edit_does_not_re_prompt(
    client, db, auth_doctor, patient_user, consultation
):
    """The usability case.

    The prescriber justified this conflict already. Adjusting a dosage is not a
    new clinical decision and must not demand the justification again.
    """
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    assert created.status_code in (200, 201), created.text

    res = await _update(
        client,
        auth_doctor,
        created.json()["id"],
        [{"medicine_name": "Penicillin V", "dosage": "250mg"}],
    )

    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_the_stored_reason_survives_an_unrelated_edit(
    client, db, auth_doctor, patient_user, consultation
):
    """A justification must not be lost by a request that did not resend it."""
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    prescription_id = created.json()["id"]

    await _update(
        client,
        auth_doctor,
        prescription_id,
        [{"medicine_name": "Penicillin V", "dosage": "250mg"}],
    )

    stored = await db.get(Prescription, prescription_id)
    await db.refresh(stored)
    assert stored.allergy_override_reason == REASON


@pytest.mark.asyncio
async def test_removing_the_allergen_clears_the_justification(
    client, db, auth_doctor, patient_user, consultation
):
    """A reason must not sit on a prescription it no longer describes."""
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    prescription_id = created.json()["id"]

    res = await _update(client, auth_doctor, prescription_id, _items("Paracetamol"))
    assert res.status_code in (200, 201), res.text

    stored = await db.get(Prescription, prescription_id)
    await db.refresh(stored)
    assert stored.allergy_override_reason is None
    assert stored.allergy_override_substances is None


@pytest.mark.asyncio
async def test_a_newly_added_allergen_still_re_prompts(
    client, db, auth_doctor, patient_user, consultation
):
    """One justified conflict must not license a second, different one."""
    await _record_allergy(db, patient_user, f"{ALLERGEN}, Metformin")

    created = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )

    res = await _update(
        client,
        auth_doctor,
        created.json()["id"],
        _items("Penicillin V", "Metformin"),
    )

    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_issue_succeeds_once_the_conflict_is_justified(
    client, db, auth_doctor, patient_user, consultation
):
    """The escape route the block points at must actually work."""
    await _record_allergy(db, patient_user, ALLERGEN)

    created = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    prescription_id = created.json()["id"]

    res = await _issue(client, auth_doctor, prescription_id)
    assert res.status_code in (200, 201), res.text

    stored = await db.get(Prescription, prescription_id)
    await db.refresh(stored)
    assert stored.status == PrescriptionStatus.ISSUED


# ---------------------------------------------------------------------------
# Substances, not typed names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relabelling_a_brand_does_not_re_prompt(
    client, db, auth_doctor, patient_user, consultation, cefim
):
    """"Cefim" to "Cefim 400mg" is not a new clinical decision.

    The snapshot holds the resolved substance, so a cosmetic relabelling of the
    same medicine does not demand a fresh justification.
    """
    await _record_allergy(db, patient_user, "Cefixime")

    created = await _create(
        client,
        auth_doctor,
        consultation,
        [{"medicine_name": "Cefim", "medicine_id": cefim.id}],
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    assert created.status_code in (200, 201), created.text

    res = await _update(
        client,
        auth_doctor,
        created.json()["id"],
        [{"medicine_name": "Cefim 400mg", "medicine_id": cefim.id}],
    )

    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_the_snapshot_stores_the_substance(
    client, db, auth_doctor, patient_user, consultation, cefim
):
    await _record_allergy(db, patient_user, "Cefixime")

    created = await _create(
        client,
        auth_doctor,
        consultation,
        [{"medicine_name": "Cefim", "medicine_id": cefim.id}],
        allergy_override=True,
        allergy_override_reason=REASON,
    )

    stored = await db.get(Prescription, created.json()["id"])
    await db.refresh(stored)
    assert stored.allergy_override_substances == ["cefixime"]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@pytest.fixture
async def allergen_template(db, auth_doctor):
    template = PrescriptionTemplate(
        doctor_id=auth_doctor["doctor"].id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        name="Standard course",
    )
    db.add(template)
    await db.flush()

    db.add(
        PrescriptionTemplateItem(
            template_id=template.id,
            medicine_name="Penicillin V",
            dosage="500mg",
        )
    )
    await db.commit()
    return template


@pytest.mark.asyncio
async def test_a_template_can_be_applied_at_all(
    client, db, auth_doctor, consultation, allergen_template
):
    """Applying a template raised MissingGreenlet — a 500 on every use.

    `.items` is a relationship, and touching it outside a greenlet fails under
    async SQLAlchemy. Nothing exercised it, so it stayed broken.
    """
    res = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Paracetamol"),
        template_id=allergen_template.id,
    )

    assert res.status_code in (200, 201), res.text
    assert len(res.json()["items"]) == 2


@pytest.mark.asyncio
async def test_a_template_medicine_is_allergy_checked(
    client, db, auth_doctor, patient_user, consultation, allergen_template
):
    """Template rows land on the prescription, so they must be checked.

    They used to be added after the check had already run.
    """
    await _record_allergy(db, patient_user, ALLERGEN)

    res = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Paracetamol"),
        template_id=allergen_template.id,
    )

    assert res.status_code == 400, res.text
    assert "penicillin" in res.text.lower()


@pytest.mark.asyncio
async def test_a_template_allergen_can_be_overridden(
    client, db, auth_doctor, patient_user, consultation, allergen_template
):
    await _record_allergy(db, patient_user, ALLERGEN)

    res = await _create(
        client,
        auth_doctor,
        consultation,
        _items("Paracetamol"),
        template_id=allergen_template.id,
        allergy_override=True,
        allergy_override_reason=REASON,
    )

    assert res.status_code in (200, 201), res.text
