"""Keeping the substance link truthful when the catalogue is written to.

The migration that introduced generics backfilled the rows that existed at the
time, and nothing maintained the link afterwards: a medicine added through the
admin API got no generic_id at all, and editing generic_name moved the
displayed substance while the link kept pointing at the old one.

Both are silent. An unlinked medicine is not an error anywhere — it simply
drops out of substance-level allergy checking, so a patient allergic to
Cefixime stops being warned about that brand and nothing says so.
"""

import pytest
from sqlalchemy import select

from app.models.generic import Generic
from app.models.medicine import Medicine
from app.services.generic_service import resolve_or_create_generic


def _payload(**overrides):
    body = {
        "name": "Zimax",
        "generic_name": "Azithromycin",
        "strength": "500mg",
        "manufacturer": "Square",
        "is_brand": True,
    }
    body.update(overrides)
    return body


async def _create(client, auth_admin, **overrides):
    return await client.post(
        "/admin/medicines",
        json=_payload(**overrides),
        headers=auth_admin["headers"],
    )


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_new_medicine_is_linked_to_its_substance(
    client, db, auth_admin
):
    res = await _create(client, auth_admin)
    assert res.status_code in (200, 201), res.text

    medicine = await db.scalar(select(Medicine).where(Medicine.name == "Zimax"))
    await db.refresh(medicine)

    assert medicine.generic_id is not None


@pytest.mark.asyncio
async def test_a_new_substance_creates_one_generic(client, db, auth_admin):
    await _create(client, auth_admin)

    generic = await db.scalar(
        select(Generic).where(Generic.normalized_name == "azithromycin")
    )
    assert generic is not None
    assert generic.name == "Azithromycin"


@pytest.mark.asyncio
async def test_two_brands_of_one_substance_share_a_generic(
    client, db, auth_admin
):
    """The point of the relation: brands of a substance must be one family."""
    await _create(client, auth_admin, name="Zimax")
    await _create(client, auth_admin, name="Azin")

    rows = (
        await db.execute(
            select(Medicine.generic_id).where(Medicine.name.in_(["Zimax", "Azin"]))
        )
    ).scalars().all()

    assert len(set(rows)) == 1
    assert rows[0] is not None


@pytest.mark.asyncio
async def test_a_differently_spelled_substance_reuses_the_same_generic(
    client, db, auth_admin
):
    """Spacing and punctuation must not split a brand family in two."""
    await _create(
        client, auth_admin, name="Moxaclav", generic_name="Amoxicillin + Clavulanic Acid"
    )
    await _create(
        client, auth_admin, name="Fimoxyclav", generic_name="amoxicillin clavulanic acid"
    )

    rows = (
        await db.execute(
            select(Medicine.generic_id).where(
                Medicine.name.in_(["Moxaclav", "Fimoxyclav"])
            )
        )
    ).scalars().all()

    assert len(set(rows)) == 1


@pytest.mark.asyncio
async def test_an_existing_generic_is_reused_not_duplicated(
    client, db, auth_admin
):
    db.add(Generic(name="Azithromycin", normalized_name="azithromycin"))
    await db.commit()

    await _create(client, auth_admin)

    count = len(
        (
            await db.scalars(
                select(Generic.id).where(Generic.normalized_name == "azithromycin")
            )
        ).all()
    )
    assert count == 1


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_the_substance_moves_the_link(client, db, auth_admin):
    """The drift case.

    Before this, generic_name showed the new substance while generic_id still
    pointed at the old one — so the allergy check tested against a substance
    the catalogue no longer claimed the medicine contained.
    """
    created = await _create(client, auth_admin)
    medicine_id = created.json()["id"]

    res = await client.put(
        f"/admin/medicines/{medicine_id}",
        json={"generic_name": "Cefixime"},
        headers=auth_admin["headers"],
    )
    assert res.status_code in (200, 201), res.text

    medicine = await db.get(Medicine, medicine_id)
    await db.refresh(medicine)

    generic = await db.get(Generic, medicine.generic_id)
    assert generic.normalized_name == "cefixime"


@pytest.mark.asyncio
async def test_editing_something_else_leaves_the_link_alone(
    client, db, auth_admin
):
    created = await _create(client, auth_admin)
    medicine_id = created.json()["id"]

    before = (await db.get(Medicine, medicine_id)).generic_id

    await client.put(
        f"/admin/medicines/{medicine_id}",
        json={"manufacturer": "Beximco"},
        headers=auth_admin["headers"],
    )

    medicine = await db.get(Medicine, medicine_id)
    await db.refresh(medicine)
    assert medicine.generic_id == before


@pytest.mark.asyncio
async def test_the_displayed_substance_and_the_link_always_agree(
    client, db, auth_admin
):
    """The invariant the whole change exists to hold."""
    created = await _create(client, auth_admin)
    medicine_id = created.json()["id"]

    await client.put(
        f"/admin/medicines/{medicine_id}",
        json={"generic_name": "Paracetamol"},
        headers=auth_admin["headers"],
    )

    medicine = await db.get(Medicine, medicine_id)
    await db.refresh(medicine)
    generic = await db.get(Generic, medicine.generic_id)

    assert generic.normalized_name == "paracetamol"
    assert medicine.generic_name == "Paracetamol"


# ---------------------------------------------------------------------------
# The resolver itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_blank_substance_resolves_to_nothing(db):
    assert await resolve_or_create_generic(db, "") is None
    assert await resolve_or_create_generic(db, None) is None
    assert await resolve_or_create_generic(db, "   ") is None


@pytest.mark.asyncio
async def test_the_resolver_is_idempotent(db):
    first = await resolve_or_create_generic(db, "Ibuprofen")
    second = await resolve_or_create_generic(db, "  IBUPROFEN  ")

    assert first.id == second.id
