import pytest
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.workers.outbox_worker import process_batch
from app.websocket.manager import manager

from app.models.outbox_event import OutboxEvent


@pytest.mark.asyncio
async def test_prescription_issued_websocket_event(
    db,
    issued_prescription_event,
    patient_user,
):

    manager.notify_user = AsyncMock()

    processed = await process_batch(db)

    assert processed >= 1

    calls = manager.notify_user.await_args_list

    assert any(
        (
            call.kwargs.get("user_id") == patient_user.id
            and call.kwargs.get("message", {}).get("event")
            == "prescription_issued"
        )
        for call in calls
    )


@pytest.mark.asyncio
async def test_prescription_updated_event_processed(
    db,
    prescription_updated_event,
):

    processed = await process_batch(db)

    assert processed >= 1

    result = await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.id == prescription_updated_event.id
        )
    )

    event = result.scalar_one()

    assert event.status == "processed"