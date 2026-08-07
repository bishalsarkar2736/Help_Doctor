"""What a patient types into the medicine assistant is never kept.

A chat box invites people to describe their health, and this one was keeping
every word — including "can i take something in place of this" — in a table
with no retention policy, surfaced to clinic admins through three analytics
reports.

The columns are gone rather than nulled, so the guarantee is structural: there
is nowhere for an accidental writer to put the text back. These tests assert
that at the schema level, which is the only level that cannot drift.

Everything the analytics need survives. Which medicine was asked about, how
often nothing matched, tokens and latency all remain — the reports are keyed on
the medicine instead of on the words.
"""

import pytest
from sqlalchemy import inspect, select

from app.models.medicine_ai_log import MedicineAILog
from app.models.medicine_assistant_query import MedicineAssistantQuery
from app.services.medicine_assistant_query_service import (
    log_medicine_assistant_query,
)


# ---------------------------------------------------------------------------
# The schema itself
# ---------------------------------------------------------------------------


def test_the_question_column_does_not_exist():
    """Structural, not a convention. A nullable column is one that can be
    filled again by a writer nobody reviewed."""
    columns = {c.key for c in inspect(MedicineAssistantQuery).columns}

    assert "question" not in columns


def test_the_ai_log_stores_neither_question_nor_answer():
    columns = {c.key for c in inspect(MedicineAILog).columns}

    assert "question" not in columns
    assert "answer" not in columns


def test_what_the_analytics_need_survives():
    """Removing the text must not remove the ability to run the product."""
    query_columns = {c.key for c in inspect(MedicineAssistantQuery).columns}
    log_columns = {c.key for c in inspect(MedicineAILog).columns}

    assert "medicine_name" in query_columns
    assert "created_at" in query_columns

    assert {"medicine_id", "medicine_name", "tokens_used", "latency_ms"} <= log_columns


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_matched_question_records_only_the_medicine(db, default_clinic):
    await log_medicine_assistant_query(
        db, clinic_id=default_clinic.id, medicine_name="Napa"
    )
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert row.medicine_name == "Napa"
    assert not hasattr(row, "question")


@pytest.mark.asyncio
async def test_an_unmatched_question_is_still_counted(db, default_clinic):
    """"How often do we fail to match" must keep working — it is the signal
    that the catalogue or its aliases need attention."""
    await log_medicine_assistant_query(
        db, clinic_id=default_clinic.id, medicine_name=None
    )
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert row.medicine_name is None
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_the_writer_will_not_accept_a_question(db, default_clinic):
    """The signature is the guard: a caller trying to pass one fails loudly
    rather than having it silently ignored."""
    with pytest.raises(TypeError):
        await log_medicine_assistant_query(
            db,
            clinic_id=default_clinic.id,
            medicine_name="Napa",
            question="I am pregnant, can I take this?",
        )


# ---------------------------------------------------------------------------
# The analytics that used to expose the text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_queries_reports_counts_not_text(db, default_clinic):
    from app.services.medicine_analytics_service import get_failed_queries

    for _ in range(3):
        await log_medicine_assistant_query(
            db, clinic_id=default_clinic.id, medicine_name=None
        )
    await log_medicine_assistant_query(
        db, clinic_id=default_clinic.id, medicine_name="Napa"
    )
    await db.commit()

    rows = await get_failed_queries(db)

    assert rows
    assert sum(r["failures"] for r in rows) == 3
    assert all("question" not in r for r in rows)


@pytest.mark.asyncio
async def test_top_questions_reports_medicines(db, default_clinic):
    """Ten people asking about Napa in ten phrasings were ten rows before and
    are one now — which is also the more useful answer."""
    from app.services.medicine_ai_analytics_service import get_top_ai_questions

    rows = await get_top_ai_questions(db, clinic_id=default_clinic.id)

    assert all("question" not in r for r in rows)
    assert all("medicine_name" in r for r in rows)


@pytest.mark.asyncio
async def test_disliked_report_names_medicines(db, default_clinic):
    from app.services.medicine_ai_analytics_service import (
        get_most_disliked_questions,
    )

    rows = await get_most_disliked_questions(db, clinic_id=default_clinic.id)

    assert all("question" not in r for r in rows)
