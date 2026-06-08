from app.models.medicine_assistant_query import (
    MedicineAssistantQuery,
)


async def log_medicine_assistant_query(
    db,
    *,
    question: str,
    medicine_name: str | None,
):

    db.add(
        MedicineAssistantQuery(
            question=question,
            medicine_name=medicine_name,
        )
    )