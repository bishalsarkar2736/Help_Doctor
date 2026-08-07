"""Recording that a question was asked, not what it said.

The question text is deliberately absent. What survives is the signal the
analytics actually use — which medicine was matched, or that nothing was — so
"what are people asking about" and "how often do we fail to match" keep working
without keeping anyone's words.
"""

from app.models.medicine_assistant_query import (
    MedicineAssistantQuery,
)


async def log_medicine_assistant_query(
    db,
    *,
    clinic_id: int,
    medicine_name: str | None,
):

    db.add(
        MedicineAssistantQuery(
            clinic_id=clinic_id,
            medicine_name=medicine_name,
        )
    )
