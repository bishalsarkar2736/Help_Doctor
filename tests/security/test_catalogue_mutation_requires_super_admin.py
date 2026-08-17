"""The medicine catalogue is one shared table, so a clinic admin must not write it.

WHAT IS WRONG
medicines, medicine_aliases, generic_aliases and generics carry no clinic_id —
verified against the schema, zero such columns on any of the four. There is one
catalogue and every tenant prescribes from it. Yet all seven mutating routes are
gated with require_roles(UserRole.ADMIN), a clinic-scoped role:

    POST   /admin/medicines/            PUT    /admin/medicines/{id}
    DELETE /admin/medicines/{id}
    POST   /admin/medicine-aliases/     DELETE /admin/medicine-aliases/{id}
    POST   /admin/generic-aliases       DELETE /admin/generic-aliases/{id}

Unlike every other admin surface, there is no clinic predicate that could be
added — the resource has no tenant. So the role gate IS the whole authorization,
and one clinic's administrator edits state the whole platform depends on.

WHAT A DELETE ACTUALLY DOES
delete_medicine fetches by primary key and deletes, with no reference check.
From the live foreign keys: medicine_aliases cascades away, and
prescription_items.medicine_id is SET NULL — on every clinic's historical
prescriptions, not only the acting clinic's. validate_prescription_allergies
resolves allergens through that medicine_id and its generic/alias linkage, so
removing or rewriting an entry degrades allergy detection platform-wide.

THE RULE
A platform-shared resource belongs to the platform plane. Mutations require
SUPER_ADMIN; reads stay with clinic staff, who need to prescribe from it.

WHAT THIS DELIBERATELY DOES NOT DO
It does not add a tenant column or per-clinic catalogues. If clinics should be
able to register their own drugs, that is a product decision needing a schema,
not a role change.
"""

import uuid

import pytest
import pytest_asyncio

from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.services.generic_service import normalize_generic_name

# No trailing slashes: the routers register the collection paths bare, and a
# trailing slash makes Starlette answer 307 instead of running the route — which
# would mean a "403" assertion could never fail for the right reason.
MEDICINES = "/admin/medicines"
MEDICINE_ALIASES = "/admin/medicine-aliases"
GENERIC_ALIASES = "/admin/generic-aliases"


@pytest_asyncio.fixture
async def catalogue(db):
    """One substance, one brand, and an alias of each kind to delete."""
    generic = Generic(
        name=f"Probeamol {uuid.uuid4().hex[:6]}",
        normalized_name=f"probeamol{uuid.uuid4().hex[:6]}",
    )
    db.add(generic)
    await db.flush()

    medicine = Medicine(
        name=f"Probex {uuid.uuid4().hex[:6]}",
        generic_name=generic.name,
        generic_id=generic.id,
        strength="500mg",
        manufacturer="Probe Labs",
        is_brand=True,
    )
    db.add(medicine)
    await db.flush()

    medicine_alias = MedicineAlias(
        medicine_id=medicine.id, alias=f"probex-{uuid.uuid4().hex[:6]}"
    )
    # normalized_alias is NOT NULL and is what the matcher looks up; built with
    # the app's own normalizer so the fixture cannot drift from the service.
    g_alias = f"probeamol-{uuid.uuid4().hex[:6]}"
    generic_alias = GenericAlias(
        generic_id=generic.id,
        alias=g_alias,
        normalized_alias=normalize_generic_name(g_alias),
    )
    db.add_all([medicine_alias, generic_alias])
    await db.flush()

    return {
        "generic": generic,
        "medicine": medicine,
        "medicine_alias": medicine_alias,
        "generic_alias": generic_alias,
    }


def _medicine_payload():
    return {
        "name": f"Probe {uuid.uuid4().hex[:8]}",
        "generic_name": f"Probesubstance {uuid.uuid4().hex[:6]}",
        "manufacturer": "Probe Labs",
        "strength": "250mg",
    }


# ---------------------------------------------------------------------------
# A clinic ADMIN must be refused every mutation
# ---------------------------------------------------------------------------
#
# Valid payloads and real target ids throughout, so a 403 cannot be confused
# with a 422 for a malformed body or a 404 for a row that was never there.


@pytest.mark.asyncio
async def test_clinic_admin_cannot_create_a_medicine(client, db, auth_admin):
    res = await client.post(
        MEDICINES, json=_medicine_payload(), headers=auth_admin["headers"]
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_update_a_medicine(
    client, db, auth_admin, catalogue
):
    res = await client.put(
        f"{MEDICINES}/{catalogue['medicine'].id}",
        json=_medicine_payload(),
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_delete_a_medicine(
    client, db, auth_admin, catalogue
):
    """THE SHARPEST CASE. This cascades the medicine's aliases away and NULLs
    prescription_items.medicine_id for every clinic that ever prescribed it."""

    medicine_id = catalogue["medicine"].id

    res = await client.delete(
        f"{MEDICINES}/{medicine_id}", headers=auth_admin["headers"]
    )

    assert res.status_code == 403, res.text

    still_there = await db.get(Medicine, medicine_id)
    assert still_there is not None, "a refused delete removed the medicine anyway"


@pytest.mark.asyncio
async def test_clinic_admin_cannot_create_a_medicine_alias(
    client, db, auth_admin, catalogue
):
    res = await client.post(
        MEDICINE_ALIASES,
        json={
            "medicine_id": catalogue["medicine"].id,
            "alias": f"probe-{uuid.uuid4().hex[:8]}",
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_delete_a_medicine_alias(
    client, db, auth_admin, catalogue
):
    alias_id = catalogue["medicine_alias"].id

    res = await client.delete(
        f"{MEDICINE_ALIASES}/{alias_id}", headers=auth_admin["headers"]
    )

    assert res.status_code == 403, res.text
    assert await db.get(MedicineAlias, alias_id) is not None


@pytest.mark.asyncio
async def test_clinic_admin_cannot_create_a_generic_alias(
    client, db, auth_admin, catalogue
):
    res = await client.post(
        GENERIC_ALIASES,
        json={
            "generic_id": catalogue["generic"].id,
            "alias": f"probe-{uuid.uuid4().hex[:8]}",
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_clinic_admin_cannot_delete_a_generic_alias(
    client, db, auth_admin, catalogue
):
    alias_id = catalogue["generic_alias"].id

    res = await client.delete(
        f"{GENERIC_ALIASES}/{alias_id}", headers=auth_admin["headers"]
    )

    assert res.status_code == 403, res.text
    assert await db.get(GenericAlias, alias_id) is not None


# ---------------------------------------------------------------------------
# SUPER_ADMIN keeps every mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_can_create_a_medicine(client, db, auth_super_admin):
    res = await client.post(
        MEDICINES, json=_medicine_payload(), headers=auth_super_admin["headers"]
    )
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_super_admin_can_update_a_medicine(
    client, db, auth_super_admin, catalogue
):
    res = await client.put(
        f"{MEDICINES}/{catalogue['medicine'].id}",
        json=_medicine_payload(),
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_super_admin_can_delete_a_medicine(
    client, db, auth_super_admin, catalogue
):
    res = await client.delete(
        f"{MEDICINES}/{catalogue['medicine'].id}",
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 204), res.text


@pytest.mark.asyncio
async def test_super_admin_can_create_a_medicine_alias(
    client, db, auth_super_admin, catalogue
):
    res = await client.post(
        MEDICINE_ALIASES,
        json={
            "medicine_id": catalogue["medicine"].id,
            "alias": f"probe-{uuid.uuid4().hex[:8]}",
        },
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_super_admin_can_delete_a_medicine_alias(
    client, db, auth_super_admin, catalogue
):
    res = await client.delete(
        f"{MEDICINE_ALIASES}/{catalogue['medicine_alias'].id}",
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 204), res.text


@pytest.mark.asyncio
async def test_super_admin_can_create_a_generic_alias(
    client, db, auth_super_admin, catalogue
):
    res = await client.post(
        GENERIC_ALIASES,
        json={
            "generic_id": catalogue["generic"].id,
            "alias": f"probe-{uuid.uuid4().hex[:8]}",
        },
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 201), res.text


@pytest.mark.asyncio
async def test_super_admin_can_delete_a_generic_alias(
    client, db, auth_super_admin, catalogue
):
    res = await client.delete(
        f"{GENERIC_ALIASES}/{catalogue['generic_alias'].id}",
        headers=auth_super_admin["headers"],
    )
    assert res.status_code in (200, 204), res.text


# ---------------------------------------------------------------------------
# Reads are unchanged — clinic staff prescribe from this catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clinic_admin_may_still_read_the_catalogue(
    client, db, auth_admin, catalogue
):
    """Only writes move. Taking reads away would break prescribing."""

    listing = await client.get(MEDICINES, headers=auth_admin["headers"])
    assert listing.status_code == 200, listing.text

    one = await client.get(
        f"{MEDICINES}/{catalogue['medicine'].id}", headers=auth_admin["headers"]
    )
    assert one.status_code == 200, one.text

    aliases = await client.get(MEDICINE_ALIASES, headers=auth_admin["headers"])
    assert aliases.status_code == 200, aliases.text

    generics = await client.get(GENERIC_ALIASES, headers=auth_admin["headers"])
    assert generics.status_code == 200, generics.text


@pytest.mark.asyncio
async def test_lower_roles_are_still_refused(
    client, db, auth_doctor, auth_receptionist, auth_patient, catalogue
):
    """Unchanged behaviour, stated so the fix cannot be mistaken for having
    widened anything: nobody below admin could write the catalogue before."""

    for principal in (auth_doctor, auth_receptionist, auth_patient):
        res = await client.post(
            MEDICINES, json=_medicine_payload(), headers=principal["headers"]
        )
        assert res.status_code == 403, (principal["user"].role, res.text)
