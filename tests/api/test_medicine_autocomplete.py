"""Prescribing autocomplete.

Two jobs. It has to FIND the medicine — including when the prescriber types the
active substance rather than a brand — and it has to return the catalogue id,
which is what turns a typed string into a real link on the prescription.
"""

import pytest

from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias


@pytest.fixture
async def catalogue(db):
    cefixime = Generic(name="Cefixime", normalized_name="cefixime")
    metformin = Generic(name="Metformin", normalized_name="metformin")
    db.add_all([cefixime, metformin])
    await db.flush()

    cefim = Medicine(
        name="Cefim",
        generic_name="Cefixime",
        generic_id=cefixime.id,
        strength="400mg",
        manufacturer="Square",
        dosage_form="Tablet",
        is_brand=True,
    )
    db.add_all(
        [
            cefim,
            Medicine(
                name="Ximebac",
                generic_name="Cefixime",
                generic_id=cefixime.id,
                strength="200mg",
                manufacturer="Beximco",
                is_brand=True,
            ),
            Medicine(
                name="Comet",
                generic_name="Metformin",
                generic_id=metformin.id,
                strength="500mg",
                manufacturer="Square",
                is_brand=True,
            ),
        ]
    )
    await db.flush()

    db.add(MedicineAlias(medicine_id=cefim.id, alias="Cefim-A"))
    await db.commit()


async def _search(client, auth, q, **params):
    response = await client.get(
        "/medicines/autocomplete",
        params={"q": q, **params},
        headers=auth["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_finds_by_brand_name(client, auth_doctor, catalogue):
    results = await _search(client, auth_doctor, "Cefim")
    assert [r["name"] for r in results] == ["Cefim"]


@pytest.mark.asyncio
async def test_finds_every_brand_of_a_typed_generic(client, auth_doctor, catalogue):
    """A doctor typing the substance means any brand of it.

    Matching brand names alone returned nothing here, because neither "Cefim"
    nor "Ximebac" contains "cefixime".
    """
    results = await _search(client, auth_doctor, "Cefixime")
    assert sorted(r["name"] for r in results) == ["Cefim", "Ximebac"]


@pytest.mark.asyncio
async def test_finds_by_alias(client, auth_doctor, catalogue):
    results = await _search(client, auth_doctor, "Cefim-A")
    assert [r["name"] for r in results] == ["Cefim"]


@pytest.mark.asyncio
async def test_returns_the_catalogue_id(client, auth_doctor, catalogue):
    """The whole point: the client sends this back instead of a typed string."""
    results = await _search(client, auth_doctor, "Cefim")
    assert isinstance(results[0]["id"], int)


@pytest.mark.asyncio
async def test_shows_the_generic_so_brands_can_be_told_apart(
    client, auth_doctor, catalogue
):
    results = await _search(client, auth_doctor, "Cefixime")
    assert {r["generic_name"] for r in results} == {"Cefixime"}


@pytest.mark.asyncio
async def test_a_name_starting_with_the_query_ranks_first(client, auth_doctor, catalogue):
    """Typing "Cef" should surface the brand, not a substance match."""
    results = await _search(client, auth_doctor, "Cef")
    assert results[0]["name"] == "Cefim"


@pytest.mark.asyncio
async def test_no_match_returns_an_empty_list(client, auth_doctor, catalogue):
    assert await _search(client, auth_doctor, "Nonexistent") == []


@pytest.mark.asyncio
async def test_a_medicine_appears_once_even_when_name_and_alias_both_match(
    client, auth_doctor, catalogue
):
    """"Cefim" matches the brand AND the alias "Cefim-A" — still one row."""
    results = await _search(client, auth_doctor, "Cefim")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_limit_is_capped(client, auth_doctor, catalogue):
    """This endpoint fires on every keystroke; it must not serve the catalogue."""
    response = await client.get(
        "/medicines/autocomplete",
        params={"q": "Cef", "limit": 5000},
        headers=auth_doctor["headers"],
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_requires_two_characters(client, auth_doctor, catalogue):
    response = await client.get(
        "/medicines/autocomplete",
        params={"q": "C"},
        headers=auth_doctor["headers"],
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_requires_authentication(client, catalogue):
    response = await client.get("/medicines/autocomplete", params={"q": "Cefim"})
    assert response.status_code == 401
