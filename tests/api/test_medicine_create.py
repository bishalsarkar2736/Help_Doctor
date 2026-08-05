"""Creating a medicine through the ORM.

Regression test. medicines.created_at is NOT NULL and the database defaults it
to CURRENT_TIMESTAMP, but the model declared neither a default nor a
server_default — so the mapper sent an explicit NULL and every ORM insert
failed. POST /admin/medicines returned 500 in production: an admin could not
add a medicine at all.

It survived a successful 320-row seed because the seeder uses a Core insert()
with an explicit values dict, which omits the column and lets the database
default apply. Only the ORM path was broken, and nothing exercised it.
"""

import pytest
from sqlalchemy import select

from app.models.medicine import Medicine


@pytest.mark.asyncio
async def test_medicine_can_be_created_through_the_orm(db):
    medicine = Medicine(
        name="ORMTestMed",
        generic_name="Testium",
        manufacturer="Test Pharma",
        is_brand=True,
    )
    db.add(medicine)
    await db.commit()
    await db.refresh(medicine)

    assert medicine.id is not None
    # The whole point: the database default has to be applied for us.
    assert medicine.created_at is not None


@pytest.mark.asyncio
async def test_admin_can_add_a_medicine(client, auth_admin, db):
    res = await client.post(
        "/admin/medicines",
        json={
            "name": "AdminAddedMed",
            "generic_name": "Testium",
            "manufacturer": "Test Pharma",
            "is_brand": True,
        },
        headers=auth_admin["headers"],
    )

    assert res.status_code in (200, 201), res.text

    stored = await db.scalar(
        select(Medicine).where(Medicine.name == "AdminAddedMed")
    )
    assert stored is not None
    assert stored.created_at is not None
