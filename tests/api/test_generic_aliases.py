"""Allergies recorded under a name the catalogue does not use.

Paracetamol and Acetaminophen are the same substance. Every brand of it in the
catalogue is filed under one of those names, so a patient whose allergy is
written as the other matched nothing at all — not the brand, not the substance.
Per-brand aliases could not fix it: the fact belongs to the substance, and
recording it against one product would lose it on the next one added.
"""

import pytest
from sqlalchemy import select

from app.domain.prescribing.allergy import find_allergy_conflicts
from app.models.appointment import AppointmentStatus
from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.models.medicine import Medicine
from app.models.patient import Patient
from app.services.medicine_lookup_service import (
    resolve_generics_for_items,
    resolve_substance_aliases,
)


@pytest.fixture
async def paracetamol(db):
    generic = Generic(name="Paracetamol", normalized_name="paracetamol")
    db.add(generic)
    await db.flush()

    db.add_all(
        [
            Medicine(
                name="Napa",
                generic_name="Paracetamol",
                generic_id=generic.id,
                strength="500mg",
                manufacturer="Beximco",
                is_brand=True,
            ),
            Medicine(
                name="Ace",
                generic_name="Paracetamol",
                generic_id=generic.id,
                strength="500mg",
                manufacturer="Square",
                is_brand=True,
            ),
        ]
    )

    db.add(
        GenericAlias(
            generic_id=generic.id,
            alias="Acetaminophen",
            normalized_alias="acetaminophen",
        )
    )
    await db.commit()
    return generic


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_an_alias_of_the_substance_is_matched():
    """The case this exists for."""
    conflicts = find_allergy_conflicts(
        "Acetaminophen",
        ["Napa"],
        {"Napa": "Paracetamol"},
        {"Paracetamol": ["Acetaminophen"]},
    )
    assert conflicts == ["Napa"]


def test_every_brand_of_the_substance_is_matched():
    conflicts = find_allergy_conflicts(
        "Acetaminophen",
        ["Napa", "Ace"],
        {"Napa": "Paracetamol", "Ace": "Paracetamol"},
        {"Paracetamol": ["Acetaminophen"]},
    )
    assert conflicts == ["Napa", "Ace"]


def test_the_substance_own_name_still_matches():
    """Adding an alias must not displace the name already being matched."""
    conflicts = find_allergy_conflicts(
        "Paracetamol",
        ["Napa"],
        {"Napa": "Paracetamol"},
        {"Paracetamol": ["Acetaminophen"]},
    )
    assert conflicts == ["Napa"]


def test_an_alias_of_another_substance_is_not_matched():
    conflicts = find_allergy_conflicts(
        "Acetaminophen",
        ["Cefim"],
        {"Cefim": "Cefixime"},
        {"Paracetamol": ["Acetaminophen"]},
    )
    assert conflicts == []


def test_aliases_are_optional():
    """Every existing caller passes three arguments; behaviour is unchanged."""
    conflicts = find_allergy_conflicts(
        "Paracetamol", ["Napa"], {"Napa": "Paracetamol"}
    )
    assert conflicts == ["Napa"]


def test_an_alias_does_not_match_inside_a_word():
    """Whole-token matching still applies to aliases."""
    conflicts = find_allergy_conflicts(
        "Ace",
        ["Aceclofenac"],
        {"Aceclofenac": "Aceclofenac"},
        {"Aceclofenac": ["Aceclofenac Sodium"]},
    )
    assert conflicts == []


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aliases_resolve_from_the_catalogue(db, paracetamol):
    resolved = await resolve_substance_aliases(db, ["Paracetamol"])
    assert resolved == {"Paracetamol": ["Acetaminophen"]}


@pytest.mark.asyncio
async def test_a_substance_with_no_aliases_is_absent(db, paracetamol):
    assert await resolve_substance_aliases(db, ["Cefixime"]) == {}


@pytest.mark.asyncio
async def test_resolution_handles_an_empty_request(db, paracetamol):
    assert await resolve_substance_aliases(db, []) == {}


@pytest.mark.asyncio
async def test_the_full_chain_from_a_typed_brand(db, paracetamol):
    """Typed brand -> substance -> alias, the way prescribing runs it."""

    class Item:
        medicine_name = "Napa"
        medicine_id = None

    generics = await resolve_generics_for_items(db, [Item()])
    aliases = await resolve_substance_aliases(db, list(generics.values()))

    assert find_allergy_conflicts(
        "Acetaminophen", ["Napa"], generics, aliases
    ) == ["Napa"]


# ---------------------------------------------------------------------------
# End to end through prescribing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prescribing_is_blocked_by_a_substance_alias(
    client, db, auth_doctor, patient_user, appointment_factory, paracetamol
):
    patient = await db.scalar(
        select(Patient).where(Patient.user_id == patient_user.id)
    )
    if patient is None:
        patient = Patient(user_id=patient_user.id)
        db.add(patient)

    # Recorded under the name the catalogue does not use.
    patient.allergies = "Acetaminophen"
    await db.commit()

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.IN_CONSULTATION,
    )

    res = await client.post(
        f"/prescriptions/appointments/{appointment.id}",
        json={"notes": "n", "items": [{"medicine_name": "Napa"}]},
        headers=auth_doctor["headers"],
    )

    assert res.status_code == 400, res.text
    assert "napa" in res.text.lower()


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete_finds_brands_by_substance_alias(
    client, auth_doctor, paracetamol
):
    res = await client.get(
        "/medicines/autocomplete",
        params={"q": "Acetaminophen"},
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 200, res.text
    assert sorted(r["name"] for r in res.json()) == ["Ace", "Napa"]


# ---------------------------------------------------------------------------
# Registering aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_can_register_an_alias(client, db, auth_admin):
    generic = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add(generic)
    await db.commit()

    res = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": generic.id, "alias": "Isobutylphenylpropanoic acid"},
        headers=auth_admin["headers"],
    )

    assert res.status_code in (200, 201), res.text
    assert res.json()["generic_name"] == "Ibuprofen"


@pytest.mark.asyncio
async def test_the_same_alias_cannot_be_registered_twice(client, db, auth_admin):
    generic = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add(generic)
    await db.commit()

    body = {"generic_id": generic.id, "alias": "Brufen Substance"}

    await client.post(
        "/admin/generic-aliases", json=body, headers=auth_admin["headers"]
    )
    second = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": generic.id, "alias": "brufen substance"},
        headers=auth_admin["headers"],
    )

    assert second.status_code == 400, second.text


@pytest.mark.asyncio
async def test_one_name_cannot_denote_two_substances(client, db, auth_admin):
    """Otherwise an allergy to it would flag medicines with no recorded reaction."""
    first = Generic(name="Paracetamol", normalized_name="paracetamol")
    second = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add_all([first, second])
    await db.commit()

    await client.post(
        "/admin/generic-aliases",
        json={"generic_id": first.id, "alias": "Acetaminophen"},
        headers=auth_admin["headers"],
    )
    clash = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": second.id, "alias": "Acetaminophen"},
        headers=auth_admin["headers"],
    )

    assert clash.status_code == 400, clash.text
    assert "different substance" in clash.text.lower()


@pytest.mark.asyncio
async def test_an_alias_equal_to_the_substance_name_is_refused(
    client, db, auth_admin
):
    generic = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add(generic)
    await db.commit()

    res = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": generic.id, "alias": "ibuprofen"},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_an_unknown_substance_is_refused(client, auth_admin):
    res = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": 999_999, "alias": "Something"},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_a_doctor_cannot_register_an_alias(client, db, auth_doctor):
    generic = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add(generic)
    await db.commit()

    res = await client.post(
        "/admin/generic-aliases",
        json={"generic_id": generic.id, "alias": "Something"},
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_an_alias_can_be_removed(client, db, auth_admin, paracetamol):
    listed = await client.get(
        "/admin/generic-aliases", headers=auth_admin["headers"]
    )
    alias_id = listed.json()[0]["id"]

    res = await client.delete(
        f"/admin/generic-aliases/{alias_id}", headers=auth_admin["headers"]
    )
    assert res.status_code == 200, res.text

    remaining = (await db.scalars(select(GenericAlias.id))).all()
    assert alias_id not in remaining
