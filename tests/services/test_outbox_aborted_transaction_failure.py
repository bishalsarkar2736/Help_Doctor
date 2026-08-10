"""A failure that poisons the transaction must still be recorded.

THE BUG, EXACTLY
A handler violates a constraint. Postgres marks the transaction ABORTED: every
subsequent statement on it raises InFailedSQLTransactionError until it is rolled
back. The worker then tried to write the failure bookkeeping — status=failed plus
the dead-letter row — on that same transaction. That raised, the batch rolled
back, the event was still PENDING, and the next poll five seconds later did it
all again.

Observed in the deployed worker: 42 non-retryable errors, 126
InFailedSQLTransactionError, 42 "Worker crashed, retrying", and ZERO dead-letter
rows. Thirty-nine events had been circling that loop for two weeks.

THE FIX
Roll back first, then do the bookkeeping on the clean transaction that follows,
and commit it before moving on. The rollback is unconditional: a non-database
failure leaves the transaction usable and the rollback is merely wasteful, while
a database failure leaves it unusable and the rollback is the only way out.
Guessing which happened is the kind of cleverness that fails quietly.

THE ABORT IS REAL HERE
These tests do not simulate the aborted state. They insert a notification with a
related_appointment_id that does not exist, which is the actual foreign key the
production failures hit, and let Postgres abort the transaction itself. Faking it
would test the mock.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.time import utc_now
from app.models.notification import Notification, NotificationCategory
from app.models.outbox_dead_letter import DeadLetterEvent
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.workers import outbox_worker
from app.workers.outbox_worker import NonRetryableError, process_batch


def _payload(**overrides) -> dict:
    payload = {
        "event_type": "APPOINTMENT_CONFIRMED",
        "schema_version": 1,
        "aggregate_type": "appointment",
        "aggregate_id": 1,
        "appointment_id": 1,
        "user_id": 1,
        "occurred_at": utc_now().isoformat(),
        "correlation_id": str(uuid.uuid4()),
    }
    payload.update(overrides)

    return payload


async def _queued(db, **overrides) -> OutboxEvent:
    """A committed pending event, exactly as a publisher leaves one.

    Committed on purpose: the worker rolls back before recording a failure, and
    an uncommitted fixture would vanish with it. Publishers always commit.
    """
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CONFIRMED",
        payload=_payload(**overrides),
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.commit()

    return event


async def _fk_violating_handler(db, event):
    """Insert a notification pointing at an appointment that does not exist.

    The real production failure: notifications_related_appointment_id_fkey. It
    aborts the transaction inside the handler, before the worker's bookkeeping
    runs, which is the whole point.
    """
    db.add(
        Notification(
            user_id=1,
            title="t",
            message="m",
            category=NotificationCategory.APPOINTMENT,
            related_appointment_id=2_000_000_000,
            event_id=event.id,
        )
    )

    try:
        await db.flush()
    except IntegrityError as exc:
        raise NonRetryableError(f"integrity violation: {exc}") from exc


async def _dead_letters(db, event_id) -> list[DeadLetterEvent]:
    rows = (
        await db.execute(
            select(DeadLetterEvent).where(
                DeadLetterEvent.original_event_id == event_id
            )
        )
    ).scalars().all()

    return list(rows)


async def _transaction_is_usable(db) -> bool:
    """Whether the session can still execute statements.

    An aborted transaction raises here; a clean one returns 1.
    """
    try:
        return (await db.scalar(text("SELECT 1"))) == 1
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The aborted transaction, and the bookkeeping that must survive it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_real_foreign_key_violation_aborts_the_transaction(db):
    """The precondition, asserted so the rest of this file cannot be testing a
    condition that no longer occurs."""
    event = await _queued(db)

    with pytest.raises(NonRetryableError):
        await _fk_violating_handler(db, event)

    assert await _transaction_is_usable(db) is False, (
        "the transaction was expected to be aborted by the FK violation"
    )

    await db.rollback()


@pytest.mark.asyncio
async def test_the_event_is_marked_failed_despite_the_aborted_transaction(
    db, monkeypatch
):
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    await process_batch(db)

    stored = await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == event.id)
    )

    assert stored == OutboxStatus.FAILED


@pytest.mark.asyncio
async def test_the_dead_letter_row_is_written(db, monkeypatch):
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    await process_batch(db)

    letters = await _dead_letters(db, event.id)

    assert len(letters) == 1
    assert letters[0].event_type == "APPOINTMENT_CONFIRMED"
    assert letters[0].payload == event.payload
    assert letters[0].error_message


@pytest.mark.asyncio
async def test_the_failure_is_durable_not_merely_in_memory(db, monkeypatch):
    """Committed, not pending in a session that a later rollback could discard.

    Read back after an explicit rollback: anything that survives that was
    genuinely committed.
    """
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    await process_batch(db)
    await db.rollback()

    stored = await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == event.id)
    )

    assert stored == OutboxStatus.FAILED
    assert len(await _dead_letters(db, event.id)) == 1


@pytest.mark.asyncio
async def test_no_in_failed_sql_transaction_error_escapes(db, monkeypatch):
    """The exception that used to end the batch. process_batch must return
    normally rather than raise it."""
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    await _queued(db)

    await process_batch(db)  # must not raise

    assert await _transaction_is_usable(db) is True


@pytest.mark.asyncio
async def test_the_event_does_not_return_to_pending(db, monkeypatch):
    """The loop's signature symptom. A dead-lettered event must be invisible to
    every later poll — both status and failed_at exclude it."""
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    for _ in range(3):
        await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.status == OutboxStatus.FAILED
    assert row.failed_at is not None
    assert len(await _dead_letters(db, event.id)) == 1, (
        "repeated polls duplicated the dead-letter record"
    )


@pytest.mark.asyncio
async def test_the_worker_goes_on_to_the_next_event(db, monkeypatch):
    """The batch stops at the failure — the rollback has expired everything still
    queued — but the worker itself carries on. The next poll picks up the healthy
    event, with the failed one now excluded.
    """
    handled: list = []

    async def _fail_first(db_, event_):
        if event_.payload.get("poison"):
            await _fk_violating_handler(db_, event_)
        handled.append(event_.id)

    monkeypatch.setattr(outbox_worker, "handle_event", _fail_first)

    poison = await _queued(db, poison=True)
    healthy = await _queued(db, poison=False)

    await process_batch(db)   # trips on the poison event
    await process_batch(db)   # the poll that follows

    assert handled == [healthy.id]

    assert await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == poison.id)
    ) == OutboxStatus.FAILED

    assert await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == healthy.id)
    ) == OutboxStatus.PROCESSED


@pytest.mark.asyncio
async def test_a_whole_queue_of_poisoned_events_drains(db, monkeypatch):
    """The production condition: thirty-nine events that can never succeed. Each
    poll must retire exactly one and leave nothing pending at the end."""
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    # Ids captured up front: process_batch rolls the session back, which expires
    # these instances, and reading .id afterwards is a lazy load from a
    # coroutine — the same trap the worker's own failure path had.
    event_ids = [(await _queued(db)).id for _ in range(5)]

    for _ in range(len(event_ids)):
        await process_batch(db)

    statuses = [
        await db.scalar(
            select(OutboxEvent.status).where(OutboxEvent.id == event_id)
        )
        for event_id in event_ids
    ]

    assert statuses == [OutboxStatus.FAILED] * 5

    for event_id in event_ids:
        assert len(await _dead_letters(db, event_id)) == 1


# ---------------------------------------------------------------------------
# Retryable failures keep their existing behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retryable_failure_still_schedules_a_retry(db, monkeypatch):
    async def _boom(db_, event_):
        raise RuntimeError("transient")

    monkeypatch.setattr(outbox_worker, "handle_event", _boom)

    event = await _queued(db)

    await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.status == OutboxStatus.PENDING
    assert row.retry_count == 1
    assert row.next_retry_at is not None
    assert row.failed_at is None
    assert await _dead_letters(db, event.id) == []


@pytest.mark.asyncio
async def test_the_retry_backoff_is_unchanged(db, monkeypatch):
    """min(2**n, 300) seconds. Pinned because the bookkeeping moved and the
    schedule must not have moved with it."""
    async def _boom(db_, event_):
        raise RuntimeError("transient")

    monkeypatch.setattr(outbox_worker, "handle_event", _boom)

    event = await _queued(db)

    before = utc_now()

    await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    delay = (row.next_retry_at - before).total_seconds()

    # retry_count becomes 1, so 2**1 = 2 seconds, with a little slack for the
    # time the batch itself took.
    assert 0 < delay <= 10


@pytest.mark.asyncio
async def test_a_retryable_failure_is_not_dead_lettered_early(db, monkeypatch):
    async def _boom(db_, event_):
        raise RuntimeError("transient")

    monkeypatch.setattr(outbox_worker, "handle_event", _boom)

    event = await _queued(db)
    event.retry_count = 0
    await db.commit()

    await process_batch(db)

    assert await _dead_letters(db, event.id) == []


@pytest.mark.asyncio
async def test_exhausted_retries_are_dead_lettered_once(db, monkeypatch):
    async def _boom(db_, event_):
        raise RuntimeError("transient")

    monkeypatch.setattr(outbox_worker, "handle_event", _boom)

    event = await _queued(db)
    event.retry_count = event.max_retries - 1
    await db.commit()

    await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.status == OutboxStatus.FAILED
    assert row.failed_at is not None
    assert len(await _dead_letters(db, event.id)) == 1


@pytest.mark.asyncio
async def test_a_non_retryable_failure_never_schedules_a_retry(db, monkeypatch):
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.next_retry_at is None
    assert row.status == OutboxStatus.FAILED


# ---------------------------------------------------------------------------
# Idempotency of the bookkeeping itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeating_the_bookkeeping_does_not_duplicate_the_dead_letter(db):
    """Called twice directly, which is what a crash between the commit and the
    next poll would amount to. original_event_id has no unique constraint, so the
    guard is the only thing standing between that and a doubled table."""
    event = await _queued(db)

    for _ in range(3):
        await outbox_worker._record_failure_out_of_band(
            db,
            event_id=event.id,
            event_type=event.event_type,
            payload=event.payload,
            error="boom",
            dead_letter=True,
            now=utc_now(),
        )

    assert len(await _dead_letters(db, event.id)) == 1


@pytest.mark.asyncio
async def test_bookkeeping_for_a_deleted_event_is_a_no_op(db):
    """Requirement 10: the bookkeeping itself failing must not take the worker
    down. A row deleted underneath the batch is the benign version."""
    event = await _queued(db)
    event_id = event.id

    await db.delete(event)
    await db.commit()

    await outbox_worker._record_failure_out_of_band(
        db,
        event_id=event_id,
        event_type="APPOINTMENT_CONFIRMED",
        payload={},
        error="boom",
        dead_letter=True,
        now=utc_now(),
    )

    assert await _dead_letters(db, event_id) == []


@pytest.mark.asyncio
async def test_the_bookkeeping_rolls_back_before_it_writes(db):
    """The ordering that is the whole fix. Poison the transaction first, then ask
    the bookkeeping to record a failure on it — it must succeed."""
    event = await _queued(db)

    # Read before poisoning: once the flush has failed, every attribute access
    # on this instance raises PendingRollbackError.
    event_id, event_type, payload = event.id, event.event_type, event.payload

    with pytest.raises(NonRetryableError):
        await _fk_violating_handler(db, event)

    assert await _transaction_is_usable(db) is False

    await outbox_worker._record_failure_out_of_band(
        db,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        error="boom",
        dead_letter=True,
        now=utc_now(),
    )

    assert await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == event_id)
    ) == OutboxStatus.FAILED


# ---------------------------------------------------------------------------
# Nothing else moved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_event_is_still_processed(db, monkeypatch):
    async def _ok(db_, event_):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    event = await _queued(db)

    processed = await process_batch(db)

    assert processed == 1

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.status == OutboxStatus.PROCESSED
    assert row.processed_at is not None
    assert row.retry_count == 0
    assert row.last_error is None


@pytest.mark.asyncio
async def test_a_dead_lettered_event_is_never_selected_again(db, monkeypatch):
    """Idempotency at the selection level: status and failed_at both exclude it,
    so it cannot be processed a second time."""
    monkeypatch.setattr(outbox_worker, "handle_event", _fk_violating_handler)

    event = await _queued(db)

    await process_batch(db)

    seen: list = []

    async def _record(db_, event_):
        seen.append(event_.id)

    monkeypatch.setattr(outbox_worker, "handle_event", _record)

    await process_batch(db)

    assert event.id not in seen


@pytest.mark.asyncio
async def test_stuck_event_recovery_still_works(db, monkeypatch):
    """The recovery sweep runs before the batch and is untouched by the failure
    path; a row abandoned in `processing` must still come back."""
    from datetime import timedelta

    async def _ok(db_, event_):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CONFIRMED",
        payload=_payload(),
        status=OutboxStatus.PROCESSING,
        processing_started_at=utc_now() - timedelta(hours=1),
    )
    db.add(event)
    await db.commit()

    await process_batch(db)

    row = await db.get(OutboxEvent, event.id)
    await db.refresh(row)

    assert row.status == OutboxStatus.PROCESSED


@pytest.mark.asyncio
async def test_the_bookkeeping_commits_on_its_own(db):
    """The helper must not depend on its caller committing afterwards.

    Written because a mutant that downgraded the helper's commit() to flush()
    survived the rest of this file: process_batch commits again in its tail
    immediately after the break, so the two are indistinguishable through that
    path. They are not indistinguishable in principle — the point of committing
    inside the helper is that the failure is durable the moment it is recorded,
    whatever the caller does next, including crashing.

    So this calls the helper directly and then ROLLS BACK. Only a committed row
    survives that.
    """
    event = await _queued(db)
    event_id, event_type, payload = event.id, event.event_type, event.payload

    await outbox_worker._record_failure_out_of_band(
        db,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        error="boom",
        dead_letter=True,
        now=utc_now(),
    )

    await db.rollback()

    assert await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == event_id)
    ) == OutboxStatus.FAILED, "the failure status was not committed"

    assert len(await _dead_letters(db, event_id)) == 1, (
        "the dead-letter row was not committed"
    )
