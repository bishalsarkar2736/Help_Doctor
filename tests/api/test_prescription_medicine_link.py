"""Prescribing a catalogue entry rather than a string.

When the prescriber picks from autocomplete, the item carries the catalogue id.
That removes the guesswork from allergy checking: instead of asking "which row
did this typed name probably mean", the check reads the substance off the row
the prescriber actually chose.

Free text stays valid throughout — a medicine the catalogue does not carry must
still be prescribable, and every row written before autocomplete existed has no
id at all.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.patient import Patient
from app.models.prescription import PrescriptionItem


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


async def _allergic_to(db, patient_user, allergen):
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


async def _prescribe(client, auth_doctor, appointment, item, **extra):
    return await client.post(
        f"/prescriptions/appointments/{appointment.id}",
        json={"notes": "test", "items": [item], **extra},
        headers=auth_doctor["headers"],
    )


@pytest.mark.asyncio
async def test_the_selected_medicine_is_stored(
    client, db, auth_doctor, consultation, cefim
):
    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Cefim 400mg", "medicine_id": cefim.id},
    )
    assert res.status_code in (200, 201), res.text

    stored = await db.scalar(
        select(PrescriptionItem).where(PrescriptionItem.medicine_name == "Cefim 400mg")
    )
    assert stored.medicine_id == cefim.id


@pytest.mark.asyncio
async def test_the_selected_medicine_drives_the_allergy_check(
    client, db, auth_doctor, patient_user, consultation, cefim
):
    """The id decides, not the spelling.

    The typed name here is "Brand X" — nothing about that string could ever be
    matched to Cefixime. Only the selected catalogue row carries the substance.
    """
    await _allergic_to(db, patient_user, "Cefixime")

    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Brand X", "medicine_id": cefim.id},
    )

    assert res.status_code == 400, res.text
    assert "cefixime" in res.text.lower()


@pytest.mark.asyncio
async def test_the_warning_names_the_substance_it_fired_for(
    client, db, auth_doctor, patient_user, consultation, cefim
):
    """"Cefim" says which line; "(Cefixime)" says why.

    A warning a prescriber cannot judge is one they dismiss.
    """
    await _allergic_to(db, patient_user, "Cefixime")

    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Cefim", "medicine_id": cefim.id},
    )

    assert res.status_code == 400, res.text
    assert "Cefim (Cefixime)" in res.text


@pytest.mark.asyncio
async def test_free_text_is_still_accepted(
    client, db, auth_doctor, consultation, cefim
):
    """A medicine the catalogue does not carry must remain prescribable."""
    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Some Imported Syrup", "dosage": "5ml"},
    )
    assert res.status_code in (200, 201), res.text

    stored = await db.scalar(
        select(PrescriptionItem).where(
            PrescriptionItem.medicine_name == "Some Imported Syrup"
        )
    )
    assert stored.medicine_id is None


@pytest.mark.asyncio
async def test_free_text_is_still_allergy_checked(
    client, db, auth_doctor, patient_user, consultation
):
    """No id must not mean no check — that is how old rows behave."""
    await _allergic_to(db, patient_user, "Penicillin")

    res = await _prescribe(
        client, auth_doctor, consultation, {"medicine_name": "Penicillin V"}
    )
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_an_unknown_medicine_id_is_refused(
    client, auth_doctor, consultation, cefim
):
    """Rejected, not silently nulled.

    Quietly dropping the link would store a prescription whose allergy check
    ran on the typed name while the request claimed a catalogue entry.
    """
    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Cefim", "medicine_id": 999_999},
    )
    assert res.status_code == 400, res.text
    assert "unknown medicine" in res.text.lower()


@pytest.mark.asyncio
async def test_a_prescriber_can_still_override_with_a_reason(
    client, db, auth_doctor, patient_user, consultation, cefim
):
    """Selecting from the catalogue must not remove the clinical judgement."""
    await _allergic_to(db, patient_user, "Cefixime")

    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Cefim", "medicine_id": cefim.id},
        allergy_override=True,
        allergy_override_reason="Reaction was mild rash; benefit outweighs risk.",
    )
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_the_response_exposes_the_link(
    client, auth_doctor, consultation, cefim
):
    """The client needs it back to keep the selection when editing a draft."""
    res = await _prescribe(
        client,
        auth_doctor,
        consultation,
        {"medicine_name": "Cefim", "medicine_id": cefim.id},
    )
    assert res.status_code in (200, 201), res.text
    assert res.json()["items"][0]["medicine_id"] == cefim.id
