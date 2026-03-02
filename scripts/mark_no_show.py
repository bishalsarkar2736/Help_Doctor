import asyncio
from app.db.session import AsyncSessionLocal
from app.services.appointment_no_show_service import mark_no_show_appointments


async def main():
    async with AsyncSessionLocal() as db:
        count = await mark_no_show_appointments(db)
        print(f"Marked {count} appointments as NO_SHOW")


if __name__ == "__main__":
    asyncio.run(main())
