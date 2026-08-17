"""Deleting a prescribed medicine silently disarms the allergy check.

WHAT DELETION DOES TODAY
delete_medicine fetches by primary key and deletes, with no reference check
(admin_medicine_service.py). From the live foreign keys:

    prescription_items.medicine_id  ON DELETE SET NULL
    medicine_aliases.medicine_id    ON DELETE CASCADE
    medicine_ai_logs.medicine_id    ON DELETE SET NULL

WHAT SURVIVES, AND WHY THAT IS NOT THE PROBLEM
Nothing clinical is lost. prescription_items.medicine_name is NOT NULL and is
untouched, the PDF renders from that name alone, and the API mapper builds every
display field from it. A NULL medicine_id is already an ordinary state — free
text prescribing produces one. Historical prescriptions keep rendering exactly
as before.

WHAT BREAKS
The route from a brand name to its active substance. resolve_generic_names
reaches the substance by joining Medicine -> Generic and
MedicineAlias -> Medicine -> Generic. Both need the Medicine row.
resolve_generics_for_items falls back from a missing id to matching the typed
name, which is how pre-autocomplete rows are still checked — but that fallback
queries the same catalogue, so deleting the row defeats the id and the name
together. The substance survives in `generics`, simply unreachable.

validate_prescription_allergies then sees no substance for that drug and raises
no conflict, so a prescriber typing that brand can be allowed to prescribe an
allergen with no warning. It bites future prescribing, not issued records: the
allergy check runs at create and at issue, never as a re-check of history.

WHAT THESE TESTS PIN
Only case 1 describes behaviour that must change. The rest are guards: the
legitimate delete, the sanctioned remedy (edit instead of delete), the
resolution paths that must keep working, the cascade boundary, and the role gate
from 24cd2fb. A fix that closes case 1 by breaking any of them is not a fix.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.models.prescription import PrescriptionItem
from app.services.medicine_lookup_service import resolve_generics_for_items

MEDICINES = "/admin/medicines"


def _typed(name, medicine_id=None):
    """The shape resolve_generics_for_items accepts: a typed name and an
    optional selected id."""
    return type("Item", (), {"medicine_name": name, "medicine_id": medicine_id})()


@pytest_asyncio.fixture
async def brand(db):
    """A brand, its substance, and a registered alias.

    The brand name shares no letters with the substance, so nothing but the
    catalogue can connect them — which is what makes the resolution assertions
    meaningful rather than incidental string matching.
    """
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
    await db.flush()

    alias = MedicineAlias(medicine_id=medicine.id, alias="cefimm")
    db.add(alias)
    await db.commit()

    return {"generic": generic, "medicine": medicine, "alias": alias}


@pytest_asyncio.fixture
async def consultation(db, auth_doctor, patient_user, appointment_factory):
    return await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.IN_CONSULTATION,
    )


@pytest_asyncio.fixture
async def prescribed(client, db, auth_doctor, consultation, brand):
    """The brand actually prescribed, so the catalogue row is REFERENCED by a
    prescription_item — the state that makes deletion destructive."""
    res = await client.post(
        f"/prescriptions/appointments/{consultation.id}",
        json={
            "notes": "integrity probe",
            "items": [
                {"medicine_name": "Cefim 400mg", "medicine_id": brand["medicine"].id}
            ],
        },
        headers=auth_doctor["headers"],
    )
    assert res.status_code in (200, 201), res.text

    item = await db.scalar(
        select(PrescriptionItem).where(
            PrescriptionItem.medicine_id == brand["medicine"].id
        )
    )
    assert item is not None, "fixture assumption: the item carries the catalogue id"
    return item


# ---------------------------------------------------------------------------
# 1. A referenced medicine must not be deletable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_a_prescribed_medicine_is_refused(
    client, db, auth_super_admin, brand, prescribed
):
    """THE ONE CASE THAT MUST CHANGE.

    Refused, and nothing moved: the row, the item's link, and the aliases are
    all still there. A 4xx that still deleted would be worse than no fix.
    """
    medicine_id = brand["medicine"].id

    res = await client.delete(
        f"{MEDICINES}/{medicine_id}", headers=auth_super_admin["headers"]
    )

    assert res.status_code in (400, 409), res.text

    assert await db.get(Medicine, medicine_id) is not None, (
        "the medicine was deleted despite being prescribed"
    )

    await db.refresh(prescribed)
    assert prescribed.medicine_id == medicine_id, (
        "the prescription item's catalogue link was severed"
    )

    aliases = (
        await db.scalars(
            select(MedicineAlias).where(MedicineAlias.medicine_id == medicine_id)
        )
    ).all()
    assert len(aliases) == 1, "the alias was cascade-deleted by a refused delete"


# ---------------------------------------------------------------------------
# 2. An unreferenced medicine stays deletable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_an_unprescribed_medicine_still_succeeds(
    client, db, auth_super_admin, brand
):
    """The legitimate workflow this must not break: removing a duplicate or a
    typo that nobody has prescribed."""
    medicine_id = brand["medicine"].id

    res = await client.delete(
        f"{MEDICINES}/{medicine_id}", headers=auth_super_admin["headers"]
    )

    assert res.status_code in (200, 204), res.text
    assert await db.get(Medicine, medicine_id) is None


# ---------------------------------------------------------------------------
# 3. Editing stays available — it is the sanctioned remedy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updating_a_prescribed_medicine_is_still_allowed(
    client, db, auth_super_admin, brand, prescribed
):
    """Correcting an entry preserves the row, so every link survives. If
    deletion is refused, this is what an operator does instead — it must work.
    """
    medicine_id = brand["medicine"].id

    res = await client.put(
        f"{MEDICINES}/{medicine_id}",
        json={
            "name": "Cefim",
            "generic_name": "Cefixime",
            "manufacturer": "Square Pharmaceuticals",
            "strength": "400mg",
        },
        headers=auth_super_admin["headers"],
    )

    assert res.status_code in (200, 201), res.text

    await db.refresh(prescribed)
    assert prescribed.medicine_id == medicine_id, (
        "an edit severed the prescription item's catalogue link"
    )
    assert await db.get(Medicine, medicine_id) is not None


# ---------------------------------------------------------------------------
# 4. Substance resolution — the safety-critical property
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_substance_resolves_while_the_medicine_is_referenced(
    db, brand, prescribed
):
    """All three routes to the active substance, asserted together.

    "Cefim" and "Cefixime" share no letters, so each of these can only succeed
    through the catalogue. These are what allergy checking reads; if a fix ever
    removes the row, all three go silent at once.
    """
    medicine_id = brand["medicine"].id

    by_id = await resolve_generics_for_items(db, [_typed("Anything", medicine_id)])
    assert by_id.get("Anything") == "Cefixime", by_id

    by_name = await resolve_generics_for_items(db, [_typed("Cefim")])
    assert by_name.get("Cefim") == "Cefixime", by_name

    by_alias = await resolve_generics_for_items(db, [_typed("cefimm")])
    assert by_alias.get("cefimm") == "Cefixime", by_alias

    # And through the stored item itself, which is what the check iterates over.
    stored = await resolve_generics_for_items(db, [prescribed])
    assert stored.get(prescribed.medicine_name) == "Cefixime", stored


# ---------------------------------------------------------------------------
# 5. The cascade boundary on a legitimate delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreferenced_delete_takes_aliases_but_keeps_the_substance(
    client, db, auth_super_admin, brand
):
    """An alias of a removed drug is meaningless and goes with it. The substance
    is shared by other brands and must not."""
    medicine_id = brand["medicine"].id
    generic_id = brand["generic"].id

    res = await client.delete(
        f"{MEDICINES}/{medicine_id}", headers=auth_super_admin["headers"]
    )
    assert res.status_code in (200, 204), res.text

    aliases = (
        await db.scalars(
            select(MedicineAlias).where(MedicineAlias.medicine_id == medicine_id)
        )
    ).all()
    assert aliases == [], "aliases outlived the medicine they alias"

    assert await db.get(Generic, generic_id) is not None, (
        "deleting one brand removed the substance every other brand shares"
    )


# ---------------------------------------------------------------------------
# 6. The role gate from 24cd2fb still holds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clinic_admin_still_cannot_delete_a_medicine(
    client, db, auth_admin, brand
):
    """Pinned here too: this finding's fix must not reopen the authorization
    boundary while adding an integrity guard."""
    medicine_id = brand["medicine"].id

    res = await client.delete(
        f"{MEDICINES}/{medicine_id}", headers=auth_admin["headers"]
    )

    assert res.status_code == 403, res.text
    assert await db.get(Medicine, medicine_id) is not None


@pytest.mark.asyncio
async def test_a_super_admin_remains_the_principal_for_catalogue_deletion(
    client, db, auth_super_admin, brand
):
    """The paired allow-case, so the guard above cannot pass by deletion being
    broken for everyone."""
    res = await client.delete(
        f"{MEDICINES}/{brand['medicine'].id}",
        headers=auth_super_admin["headers"],
    )

    assert res.status_code in (200, 204), res.text
