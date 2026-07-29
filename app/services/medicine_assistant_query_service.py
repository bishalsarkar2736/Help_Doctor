from app.models.medicine_assistant_query import (
    MedicineAssistantQuery,
)


async def log_medicine_assistant_query(
    db,
    *,
    clinic_id: int,
    question: str,
    medicine_name: str | None,
):

    db.add(
        MedicineAssistantQuery(
            clinic_id=clinic_id,
            question=question,
            medicine_name=medicine_name,
        )
    )