import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.postgres import AsyncSessionLocal

from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias


ALIASES = [
    {
        "medicine_name": "Napa",
        "alias": "Paracetamol",
    },
    {
        "medicine_name": "Ace",
        "alias": "Paracetamol",
    },
    {
        "medicine_name": "Seclo",
        "alias": "Omeprazole",
    },
    {
        "medicine_name": "Maxpro",
        "alias": "Esomeprazole",
    },
]



async def seed_medicine_aliases():

    async with AsyncSessionLocal() as db:

        rows_to_insert = []

        for item in ALIASES:

            result = await db.execute(
                select(Medicine.id)
                .where(
                    Medicine.name
                    == item["medicine_name"]
                )
            )

            medicine_id = result.scalar_one_or_none()

            if not medicine_id:
                print(
                    f"Medicine not found: "
                    f"{item['medicine_name']}"
                )
                continue

            rows_to_insert.append(
                {
                    "medicine_id": medicine_id,
                    "alias": (
                        item["alias"]
                        .strip()
                        .lower()
                    ),
                }
            )

        if not rows_to_insert:
            print("Nothing to insert")
            return

        stmt = insert(
            MedicineAlias
        ).values(
            rows_to_insert
        )

        stmt = stmt.on_conflict_do_nothing(
            constraint=
            "uq_medicine_aliases_medicine_id_alias"
        )

        result = await db.execute(stmt)

        await db.commit()

        print(
            f"Inserted aliases: "
            f"{result.rowcount or 0}"
        )


async def main():
    await seed_medicine_aliases()


if __name__ == "__main__":
    asyncio.run(main())