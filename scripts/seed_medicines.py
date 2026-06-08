import asyncio
import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.db.postgres import AsyncSessionLocal
from app.models.medicine import Medicine


DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "medicines.json"
)


def load_medicines() -> list[dict]:

    with open(
        DATA_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)
    


async def seed_medicines():

    medicines = load_medicines()

    async with AsyncSessionLocal() as db:

        stmt = insert(Medicine).values(
            medicines
        )

        stmt = stmt.on_conflict_do_nothing(
            index_elements=["name"]
        )

        result = await db.execute(stmt)

        await db.commit()

        print(
            f"Inserted medicines: "
            f"{result.rowcount or 0}"
        )



async def main():
    await seed_medicines()


if __name__ == "__main__":
    asyncio.run(main())