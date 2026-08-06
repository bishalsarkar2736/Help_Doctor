import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.postgres import AsyncSessionLocal
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.services.generic_service import resolve_or_create_generic


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
    """Load the catalogue, with every medicine linked to its substance.

    The link is built HERE, not left to the migration that introduced it. That
    migration backfills rows already in the table, so on a fresh environment it
    runs against an empty catalogue and links nothing — then this script would
    insert several hundred medicines with a null generic_id, and every one of
    them would be invisible to substance-level allergy checking. Staging and
    production are exactly the environments that get seeded from empty.
    """
    medicines = load_medicines()

    async with AsyncSessionLocal() as db:

        stmt = insert(Medicine).values(medicines)

        stmt = stmt.on_conflict_do_nothing(
            index_elements=["name"]
        )

        result = await db.execute(stmt)

        # Linked from what actually landed in the table, rather than from the
        # file. The file carries more rows than distinct names, so some are
        # skipped on conflict — deriving generics from the file would create
        # substances that no medicine references.
        #
        # Driving off generic_id IS NULL also repairs rows inserted by earlier
        # runs of this script, which on_conflict_do_nothing would never revisit.
        unlinked = (
            await db.scalars(
                select(Medicine).where(Medicine.generic_id.is_(None))
            )
        ).all()

        linked = 0

        for medicine in unlinked:
            generic = await resolve_or_create_generic(
                db,
                medicine.generic_name,
            )

            if generic:
                medicine.generic_id = generic.id
                linked += 1

        await db.commit()

        total_generics = len(
            (await db.scalars(select(Generic.id))).all()
        )

        print(
            f"Inserted medicines: "
            f"{result.rowcount or 0}"
        )
        print(f"Linked to a substance: {linked}")
        print(f"Generics now: {total_generics}")



async def main():
    await seed_medicines()


if __name__ == "__main__":
    asyncio.run(main())