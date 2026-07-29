import pytest
import sqlalchemy as sa
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.time import UTC

from app.models.outbox_event import OutboxEvent
from app.models.outbox_dead_letter import DeadLetterEvent

from app.workers.outbox_worker import (
    process_batch,
)


async def create_event(
    db,
    *,
    event_type="TEST_EVENT",
    status="pending",
    retry_count=0,
    max_retries=5,
    next_retry_at=None,
    payload=None, 
):
    """
    Create a minimal OutboxEvent.

    Worker retry tests mock handle_event(), so the payload
    does not need to satisfy any event schema.
    """

    if payload is None:
        payload = {
            "id": str(uuid4()),
        }


    event = OutboxEvent(
        event_type=event_type,
        payload=payload,
        status=status,
        retry_count=retry_count,
        max_retries=max_retries,
        next_retry_at=next_retry_at,
    )

    db.add(event)

    await db.flush()

    return event


async def reload_event(
    db,
    event: OutboxEvent,
):
    await db.refresh(event)
    return event


@pytest.mark.asyncio
async def test_retry_success(db):
    """
    First processing fails -> event remains pending.
    Second processing succeeds -> event becomes processed.
    """
    # count = await db.scalar(
    #     select(sa.func.count())
    #     .select_from(OutboxEvent)
    # )

    # assert count == 0
   
    rows = (
        await db.execute(
            select(OutboxEvent)
        )
    ).scalars().all()

    assert len(rows) == 0


    event = await create_event(db)
    await db.commit()

    calls = 0

    async def fake_handle_event(db, event):
        nonlocal calls

        calls += 1

        if calls == 1:
            raise Exception("temporary provider failure")

        return None

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(side_effect=fake_handle_event),
    ):

        # -------------------------
        # First run -> failure
        # -------------------------
        processed = await process_batch(db)

        await db.refresh(event) 
        assert event.status == "pending" 
        assert event.retry_count == 1

        await reload_event(db, event)

        assert event.status == "pending"
        assert event.retry_count == 1
        assert event.failed_at is None
        assert event.last_error == "temporary provider failure"
        assert event.next_retry_at is not None

        # Make retry immediately eligible
        event.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

        # -------------------------
        # Second run -> success
        # -------------------------
        processed = await process_batch(db)

        assert processed == 1

        await reload_event(db, event)

        assert event.status == "processed"
        assert event.retry_count == 0
        assert event.last_error is None
        assert event.failed_at is None
        assert event.processing_started_at is None
        assert event.next_retry_at is None
        assert event.processed_at is not None

    assert calls == 2


@pytest.mark.asyncio
async def test_retry_counter_reset_after_success(db):
    """
    A previously retried event should have its retry_count
    reset back to zero after successful processing.
    """

    event = await create_event(
        db,
        retry_count=3,
        status="pending",
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.dispatch_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    await db.refresh(event) 
    assert event.status == "processed" 
    assert event.retry_count == 0

    await db.refresh(event)

    assert event.status == "processed"
    assert event.retry_count == 0
    assert event.last_error is None
    assert event.failed_at is None
    assert event.next_retry_at is None
    assert event.processing_started_at is None
    assert event.processed_at is not None



@pytest.mark.asyncio
async def test_retry_processes_only_pending_events(db):
    """
    Worker should process only eligible pending events.

    It must ignore:
      - processed
      - failed
      - processing
      - pending events scheduled for future retry
    """

    # Eligible pending event
    pending_event = await create_event(db)

    # Already processed
    processed_event = await create_event(
        db,
        status="processed",
    )

    # Permanently failed
    failed_event = await create_event(
        db,
        status="failed",
    )

    # Currently processing
    processing_event = await create_event(
        db,
        status="processing",
    )
    processing_event.processing_started_at = datetime.now(UTC)

    # Retry scheduled for the future
    future_retry = await create_event(
        db,
        next_retry_at=datetime.now(UTC)
        + timedelta(minutes=5),
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    # Only one eligible event should be processed
    await db.refresh(pending_event) 
    assert pending_event.status == "processed"

    await reload_event(db, pending_event)
    await reload_event(db, processed_event)
    await reload_event(db, failed_event)
    await reload_event(db, processing_event)
    await reload_event(db, future_retry)

    # Eligible event processed
    assert pending_event.status == "processed"
    assert pending_event.retry_count == 0
    assert pending_event.processed_at is not None

    # Already processed event unchanged
    assert processed_event.status == "processed"

    # Failed event unchanged
    assert failed_event.status == "failed"

    # Processing event unchanged
    assert processing_event.status == "processing"
    assert processing_event.processing_started_at is not None

    # Future retry event untouched
    assert future_retry.status == "pending"
    assert future_retry.processed_at is None
    assert future_retry.next_retry_at is not None



@pytest.mark.asyncio
async def test_retry_until_dead_letter(db):
    """
    Event should eventually move to the Dead Letter Queue
    after reaching max_retries.
    """

    event = await create_event(
        db,
        retry_count=4,
        max_retries=5,
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(
            side_effect=Exception("provider unavailable")
        ),
    ):

        processed = await process_batch(db)

    assert processed == 0

    await reload_event(db, event)

    assert event.status == "failed"
    assert event.retry_count == 5
    assert event.failed_at is not None
    assert event.last_error == "provider unavailable"
    assert event.next_retry_at is None

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id
        )
    )

    dlq = result.scalar_one()

    assert dlq.event_type == event.event_type
    assert dlq.retry_count == 5
    assert dlq.max_retries == 5
    assert dlq.error_message == "provider unavailable"



@pytest.mark.asyncio
async def test_retry_schedules_next_retry(db):
    """
    Failed events below max_retries should
    be scheduled for retry.
    """

    event = await create_event(
        db,
        retry_count=1,
        max_retries=5,
    )

    await db.commit()

    before = datetime.now(UTC)

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(
            side_effect=Exception("temporary failure")
        ),
    ):

        processed = await process_batch(db)

    assert processed == 0

    await reload_event(db, event)

    assert event.status == "pending"
    assert event.retry_count == 2

    assert event.next_retry_at is not None
    assert event.next_retry_at > before

    assert event.failed_at is None


@pytest.mark.asyncio
async def test_dead_letter_created_once(db):
    """
    DeadLetterEvent should only be created once
    for a failed event.
    """

    event = await create_event(
        db,
        retry_count=4,
        max_retries=5,
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(
            side_effect=Exception("fatal")
        ),
    ):

        await process_batch(db)

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id
        )
    )

    rows = result.scalars().all()

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_dead_letter_preserves_payload(db):
    """
    Dead letter should preserve
    the original event payload.
    """

    payload = {
        "hello": "world",
        "value": 123,
    }

    event = await create_event(db)

    event.payload = payload
    event.retry_count = 4
    event.max_retries = 5

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(
            side_effect=Exception("boom")
        ),
    ):

        await process_batch(db)

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id
        )
    )

    dlq = result.scalar_one()

    assert dlq.payload == payload


@pytest.mark.asyncio
async def test_schema_validation_failure_goes_to_dead_letter(
    db,
):
    event = OutboxEvent(
        event_type="APPOINTMENT_CONFIRMED",
        payload={
            # Missing required fields intentionally
            "foo": "bar",
        },
        max_retries=5,
    )

    db.add(event)
    await db.commit()

    processed = await process_batch(db)

    assert processed == 0

    await db.refresh(event)

    assert event.status == "failed"
    assert event.failed_at is not None
    assert event.processing_started_at is None

    assert "schema validation failed" in event.last_error

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id
        )
    )

    dlq = result.scalar_one()

    assert dlq.event_type == event.event_type
    assert dlq.retry_count == 1


@pytest.mark.asyncio
async def test_unsupported_event_is_processed(
    db,
):
    """
    Unknown event types should be skipped and marked
    as processed instead of being retried.
    """

    event = await create_event(
        db,
        event_type="UNKNOWN_EVENT",
    )

    await db.commit()

    processed = await process_batch(db)

    assert processed == 1

    await reload_event(db, event)

    assert event.status == "processed"
    assert event.processed_at is not None

    assert event.retry_count == 0
    assert event.failed_at is None
    assert event.last_error is None
    assert event.processing_started_at is None
    assert event.next_retry_at is None

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id,
        )
    )

    dead_letter = result.scalar_one_or_none()

    assert dead_letter is None


@pytest.mark.asyncio
async def test_duplicate_integrity_error_is_ignored(db):
    """
    Duplicate notifications (IntegrityError) should not
    retry the event.

    The worker should consider the event successfully
    processed because the operation is idempotent.
    """

    payload = {
        "event_type": "APPOINTMENT_CONFIRMED",

        "schema_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),

        "aggregate_type": "appointment",
        "aggregate_id": 1,

        "correlation_id": None,
        "causation_id": None,

        "actor": {
            "id": 1,
            "role": "SYSTEM",
        },

        "user_id": 1,
        "appointment_id": 1,
    }

    event = await create_event(
        db,
        event_type="APPOINTMENT_CONFIRMED",
        payload=payload,
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.dispatch_event",
        new=AsyncMock(
            side_effect=sa.exc.IntegrityError(
                statement=None,
                params=None,
                orig=Exception("duplicate"),
            )
        ),
    ):

        processed = await process_batch(db)

    assert processed == 1

    await reload_event(db, event)

    assert event.status == "processed"
    assert event.retry_count == 0
    assert event.failed_at is None
    assert event.last_error is None
    assert event.next_retry_at is None
    assert event.processed_at is not None

    result = await db.execute(
        select(DeadLetterEvent).where(
            DeadLetterEvent.original_event_id == event.id
        )
    )

    assert result.scalar_one_or_none() is None


import app.workers.outbox_worker as worker


@pytest.mark.asyncio
async def test_stuck_processing_event_is_recovered(db):
    """
    Events stuck in 'processing' longer than PROCESSING_TIMEOUT
    should be recovered and processed.
    """

    event = await create_event(
        db,
        status="processing",
    )

    event.processing_started_at = (
        datetime.now(UTC)
        - worker.PROCESSING_TIMEOUT
        - timedelta(seconds=5)
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    assert processed == 1

    await reload_event(db, event)

    assert event.status == "processed"
    assert event.processing_started_at is None
    assert event.processed_at is not None


@pytest.mark.asyncio
async def test_recent_processing_event_not_recovered(db):
    """
    Recently processing events must not be recovered.
    """

    event = await create_event(
        db,
        status="processing",
    )

    event.processing_started_at = (
        datetime.now(UTC)
        - timedelta(seconds=30)
    )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    assert processed == 0

    await reload_event(db, event)

    assert event.status == "processing"
    assert event.processed_at is None


@pytest.mark.asyncio
async def test_batch_processes_multiple_events(db):
    """
    Multiple pending events should all be processed.
    """

    events = []

    for _ in range(5):
        events.append(
            await create_event(db)
        )

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    assert processed == 5

    for event in events:
        await reload_event(db, event)

        assert event.status == "processed"
        assert event.processed_at is not None


@pytest.mark.asyncio
async def test_batch_commit_after_processing(db):
    """
    Processed events should be committed to the database.
    """

    events = [
        await create_event(db)
        for _ in range(3)
    ]

    await db.commit()

    with patch(
        "app.workers.outbox_worker.handle_event",
        new=AsyncMock(),
    ):
        processed = await process_batch(db)

    assert processed == 3

    result = await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.status == "processed"
        )
    )

    processed_events = result.scalars().all()

    assert len(processed_events) >= 3