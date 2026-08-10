import logging
from datetime import datetime, timedelta
import time
from app.core.time import UTC
import sqlalchemy as sa
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.postgres import AsyncSessionLocal
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.outbox_dead_letter import DeadLetterEvent
from app.services.notification_service import notify_user
from time import time as now_ts
from app.core.metrics import (
    outbox_events_processed_total,
    outbox_event_failures_total,
    outbox_processing_time_seconds,
    outbox_dead_letter_total,
    outbox_event_lag_seconds,
    outbox_queue_size,
    outbox_worker_heartbeat,
    outbox_stuck_events,
)
from app.schemas.event_registry import (
    EVENT_SCHEMAS,
)
from app.services.event_handlers.dispatcher import (
    dispatch_event,
)

from app.core.correlation import (
    correlation_id_ctx,
)

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.tracing import (
    inject_trace_attributes,
)



logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)

PROCESSING_TIMEOUT = timedelta(minutes=5)
BATCH_SIZE = 100
BATCH_COMMIT_SIZE = 50


# =========================
# CUSTOM EXCEPTION
# =========================
class NonRetryableError(Exception):
    """Raised for invalid events that should NOT be retried"""
    pass


async def _record_failure_out_of_band(
    db: AsyncSession,
    *,
    event_id,
    event_type: str,
    payload: dict,
    error: str,
    dead_letter: bool,
    next_retry_at=None,
    now,
) -> None:
    """Persist a failure using a transaction that is guaranteed to be clean.

    WHY THIS EXISTS
    A handler that violates a constraint leaves Postgres with an ABORTED
    transaction: every subsequent statement on it fails with
    InFailedSQLTransactionError until it is rolled back. The failure bookkeeping
    — status=failed, the dead-letter row — was being written on that same
    transaction, so it raised, the whole batch rolled back, the event stayed
    PENDING, and the worker retried it forever. 39 events had been circling that
    loop; the logs showed 42 non-retryable errors, 126 InFailedSQLTransactionError
    and zero dead-letter rows.

    THE ROLLBACK COMES FIRST, ALWAYS
    Unconditionally, not only when the session looks poisoned. A non-database
    failure leaves the transaction usable and the rollback is then merely
    wasteful; a database failure leaves it unusable and the rollback is the only
    way out. Guessing which one happened is exactly the sort of cleverness that
    breaks quietly, and this is a failure path — correctness beats a few
    redundant round trips.

    WHY THE SAME SESSION, AND NOT A SECOND ONE
    Once rolled back, the session is clean and begins a fresh transaction on its
    next statement. A second AsyncSessionLocal would take another connection from
    a pool sized per process, and would buy nothing: there is nothing left to
    preserve on the first one, because the rollback has already discarded it.

    STATE IS PASSED IN, NOT READ OFF THE ORM OBJECT
    The rollback expires every instance in the session, so reading
    event.event_type afterwards would emit a lazy SELECT. Callers capture the
    scalars before failing, and this function re-reads the row by primary key.
    """
    await db.rollback()

    row = await db.get(OutboxEvent, event_id)

    if row is None:
        # Deleted underneath us — nothing to record, and nothing wrong.
        logger.warning(
            "outbox_failure_target_missing",
            extra={"event_id": str(event_id), "event_type": event_type},
        )
        return

    row.retry_count += 1
    row.last_error = error[:500]
    row.processing_started_at = None

    if dead_letter:
        row.status = OutboxStatus.FAILED
        row.failed_at = now
        row.next_retry_at = None

        # Guarded rather than blind. original_event_id carries no unique
        # constraint, so a second pass through here — a crash between this commit
        # and the next poll, say — would otherwise leave two dead-letter rows for
        # one event and double every count taken off that table.
        already = await db.scalar(
            select(DeadLetterEvent.id).where(
                DeadLetterEvent.original_event_id == event_id
            )
        )

        if already is None:
            db.add(
                DeadLetterEvent(
                    original_event_id=event_id,
                    event_type=event_type,
                    payload=payload,
                    retry_count=row.retry_count,
                    max_retries=row.max_retries,
                    error_message=error[:500],
                )
            )

            outbox_dead_letter_total.inc()
    else:
        row.status = OutboxStatus.PENDING
        row.next_retry_at = next_retry_at

    # Committed here and only here. The failure is durable before the loop moves
    # on, so nothing later in the batch can roll it back.
    await db.commit()


# =========================
# MAIN BATCH PROCESSOR
# =========================
async def process_batch(db: AsyncSession) ->int:

    now = datetime.now(UTC)
    timeout_threshold = now - PROCESSING_TIMEOUT

    # =========================
    # 1. RECOVER STUCK EVENTS
    # =========================
    recovered = await db.execute(
        sa.update(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxStatus.PROCESSING,
            OutboxEvent.failed_at.is_(None),
            OutboxEvent.processing_started_at.is_not(None),
            OutboxEvent.processing_started_at < timeout_threshold,
        )
        .values(
            status=OutboxStatus.PENDING,
            processing_started_at=None,
            last_error=None,
        )
    )

    recovered_count = recovered.rowcount or 0
    outbox_stuck_events.set(recovered_count)

    if recovered_count:
        logger.warning(
            "outbox_stuck_events_recovered",
            extra={
                "count": recovered_count
            },
        )

    # =========================
    # 2. QUEUE SIZE
    # =========================
    count_result = await db.execute(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxStatus.PENDING,
            OutboxEvent.failed_at.is_(None),
        )
    )
    queue_size = count_result.scalar_one()

    outbox_queue_size.set(queue_size or 0)

    logger.info(
        "outbox_queue_size", 
        extra={
            "size": queue_size
        },
    )


     # 3. Fetch batch
    result = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxStatus.PENDING,
            OutboxEvent.failed_at.is_(None),
            or_(
                OutboxEvent.next_retry_at.is_(None),
                OutboxEvent.next_retry_at <= now,
            ),
        )
        .order_by(OutboxEvent.created_at.asc())
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )

    events = result.scalars().all()

    processed_count = 0
    processed_since_commit = 0
    dlq_batch: list[DeadLetterEvent] = []

    for event in events:

        payload = event.payload or {}

        # Captured BEFORE the handler runs. A failure rolls the session back and
        # expires every instance in it, so reading these off `event` afterwards
        # would emit a lazy SELECT from inside an except block.
        event_id = event.id
        event_type = event.event_type
        retry_count = event.retry_count
        max_retries = event.max_retries

        try:
            event.status = OutboxStatus.PROCESSING
            event.processing_started_at = now
            await db.flush()

            # This record already existed, carrying every field the two removed
            # prints did except one. So the replacement for
            #
            #     print("PROCESSING EVENT:", event.event_type)
            #     print("EVENT PAYLOAD:", event.payload)
            #
            # is a single key here rather than a second log line: the prints were
            # duplicating a structured record that was three lines above them.
            #
            # KEYS, never the body. These payloads carry a cancellation reason
            # typed by staff, a refund amount, prescription and patient ids — the
            # event body is the last thing that should sit in a container log.
            # payload_keys still answers "did this event carry the field I
            # expect?", which is what the payload print was used for.
            logger.info(
                "processing_event",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "retry_count": event.retry_count,
                    "correlation_id": payload.get("correlation_id"),
                    "payload_keys": sorted(payload),
                },
            )

            with tracer.start_as_current_span(
                "process_outbox_event"
            ) as span:
                
                inject_trace_attributes()
                
                try:

                    span.set_attribute(
                        "event_id",
                        str(event.id),
                    )

                    span.set_attribute(
                        "event_type",
                        event.event_type,
                    )

                    span.set_attribute(
                        "retry_count",
                        event.retry_count,
                    )

                    span.set_attribute(
                        "correlation_id",
                        payload.get("correlation_id") or "",
                    )

                    await handle_event(
                        db,
                        event,
                    )

                    span.set_status(
                        Status(StatusCode.OK)
                    )

                except Exception as e:

                    span.record_exception(e)

                    span.set_status(
                        Status(
                            StatusCode.ERROR,
                            str(e),
                        )
                    )

                    raise

            event.status = OutboxStatus.PROCESSED
            event.processed_at = now
            event.processing_started_at = None
            event.next_retry_at = None
            event.last_error = None
            event.retry_count = 0

            lag = (event.processed_at - event.created_at).total_seconds()

            outbox_event_lag_seconds.observe(lag)
            outbox_events_processed_total.inc()

            processed_count += 1
            processed_since_commit += 1

            await db.flush()

        except NonRetryableError as exc:
            # Keys, not the body — same reason as the processing record above.
            # This is the path a dead-lettered event takes, so it is exactly the
            # record a human goes and reads; the payload itself is preserved in
            # full on the DeadLetterEvent row below, which is what a replay needs
            # and is reachable through the database rather than the log stream.
            logger.error(
                "outbox_non_retryable_error",
                extra={
                    # Captured locals only. Reading event.payload here touched a
                    # session whose flush had already failed, and SQLAlchemy
                    # raised PendingRollbackError from inside the handler for the
                    # original error — turning a recorded failure back into an
                    # escaping one.
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "error": str(exc),
                    "payload_keys": sorted(payload),
                    "correlation_id": payload.get("correlation_id"),
                },
            )

            # Rolled back and committed on a clean transaction. The handler may
            # have aborted this one — an FK or unique violation does — and
            # writing the failure onto an aborted transaction is what made these
            # events immortal.
            await _record_failure_out_of_band(
                db,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                error=str(exc),
                dead_letter=True,
                now=now,
            )

            # The rollback above discarded everything this batch had not yet
            # committed, so the objects still queued are expired and the events
            # already handled are pending again. Both are picked up by the next
            # poll, five seconds away, with this event now FAILED and therefore
            # excluded. Continuing to iterate expired instances instead would
            # emit lazy loads from a coroutine and fail in a far more confusing
            # way than a short pause.
            break

        except Exception as exc:
            logger.exception(
                "outbox_event_failed",
                extra={
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "correlation_id": payload.get("correlation_id"),
                },
            )

            outbox_event_failures_total.inc()

            # retry_count is incremented inside the bookkeeping, so this reads
            # the value it is ABOUT to become.
            attempt = retry_count + 1
            exhausted = attempt >= max_retries

            # Unchanged backoff: min(2**n, 300) seconds, capped at five minutes.
            next_retry_at = (
                None
                if exhausted
                else now + timedelta(seconds=min(2 ** attempt, 300))
            )

            await _record_failure_out_of_band(
                db,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                error=str(exc),
                dead_letter=exhausted,
                next_retry_at=next_retry_at,
                now=now,
            )

            if exhausted:
                logger.critical(
                    "outbox_event_dead_letter",
                    extra={
                        "event_id": str(event_id),
                        "event_type": event_type,
                        "retry_count": attempt,
                        "correlation_id": payload.get("correlation_id"),
                    },
                )
            else:
                logger.warning(
                    "outbox_retry_scheduled",
                    extra={
                        "event_id": str(event_id),
                        "retry_count": attempt,
                        # isoformat, because JsonFormatter cannot serialise a
                        # datetime and the record was being dropped entirely.
                        "next_retry_at": (
                            next_retry_at.isoformat() if next_retry_at else None
                        ),
                        "correlation_id": payload.get("correlation_id"),
                    },
                )

            break

        if processed_since_commit >= BATCH_COMMIT_SIZE:

            if dlq_batch:

                db.add_all(dlq_batch)
                dlq_batch.clear()

            await db.flush()
            await db.commit()

            processed_since_commit = 0

    if dlq_batch:
        db.add_all(dlq_batch)

    await db.flush()
    await db.commit()

    return processed_count


# Postgres SQLSTATE classes, as reported by the driver. Read from the exception
# rather than matched in its message, which changes with wording and locale.
_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"

# The one conflict that is an expected outcome rather than a fault: two
# deliveries of the same event racing to write the same recipient's
# notification. create_notification already guards it with ON CONFLICT DO
# NOTHING; this catches the case where the insert happens elsewhere in the
# handler's transaction.
_DUPLICATE_NOTIFICATION_CONSTRAINT = "uq_notification_event_user"


def _integrity_details(exc: IntegrityError) -> tuple[str | None, str | None]:
    """SQLSTATE and constraint name, however deep the driver buries them.

    asyncpg exposes both, but SQLAlchemy wraps its exception, so the useful
    attributes sit on `.orig` or on that object's `__cause__` depending on the
    path. Read defensively: an unrecognised shape returns (None, None) and is
    then treated as unexpected, which is the safe direction.
    """
    orig = getattr(exc, "orig", None)
    cause = getattr(orig, "__cause__", None)

    sqlstate = (
        getattr(orig, "sqlstate", None)
        or getattr(orig, "pgcode", None)
        or getattr(cause, "sqlstate", None)
    )

    constraint = getattr(cause, "constraint_name", None) or getattr(
        orig, "constraint_name", None
    )

    return sqlstate, constraint


async def handle_event(db: AsyncSession, event: OutboxEvent) -> None:

    payload = event.payload or {}


    if not payload:
        raise NonRetryableError("empty payload")
    
    correlation_id_ctx.set(
        payload.get("correlation_id")
    )


    normalized_event_type = (
        event.event_type.upper()
    )

    # schema = EVENT_SCHEMAS.get(
    #     event.event_type
    # )

    schema = EVENT_SCHEMAS.get(
        normalized_event_type
    )
   
    
    if not schema:
        logger.info(
            "skipping_unsupported_event",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "correlation_id": payload.get("correlation_id"),
            },
        )

        event.status = OutboxStatus.PROCESSED
        event.processed_at = datetime.now(UTC)

        return
    
    try:

        validated = schema.model_validate(
            payload
        )

    except Exception as exc:

        # Keys, not the body. The validation error names the offending fields
        # already, and the payload is preserved on the dead-letter row.
        logger.error(
            "event_schema_validation_failed",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "payload_keys": sorted(payload or {}),
                "error": str(exc),
                "correlation_id": payload.get("correlation_id"),
            },
        )

        raise NonRetryableError(
            f"schema validation failed: {exc}"
        )


    try:
        
        await dispatch_event(
            db=db,
            #event_type=event.event_type,
            event_type=normalized_event_type,
            validated=validated,
            event_id=event.id,
        )

    except IntegrityError as exc:
        # Every IntegrityError used to be logged as a skipped duplicate and
        # swallowed, so the event was marked processed whatever had actually
        # gone wrong. A foreign key violation — a notification referencing an
        # appointment that does not exist — was reported as a duplicate and the
        # event disappeared: no retry, no dead letter, no notification, and a
        # log line naming the wrong cause.
        sqlstate, constraint = _integrity_details(exc)

        is_duplicate_notification = (
            sqlstate == _UNIQUE_VIOLATION
            and constraint == _DUPLICATE_NOTIFICATION_CONSTRAINT
        )

        if is_duplicate_notification:
            # Expected and idempotent: the recipient already has this
            # notification. Unchanged behaviour, and the only case that is
            # still swallowed.
            logger.info(
                "duplicate_notification_skipped",
                extra={
                    "event_id": str(event.id),
                    "correlation_id": payload.get("correlation_id"),
                },
            )

            return

        logger.error(
            "outbox_integrity_error",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "correlation_id": payload.get("correlation_id"),
                "sqlstate": sqlstate,
                "constraint": constraint,
            },
        )

        if sqlstate == _FOREIGN_KEY_VIOLATION:
            # The event references a row that does not exist. Retrying cannot
            # conjure it, so this goes straight to the dead letter queue by the
            # same route a failed schema validation does, rather than burning
            # five attempts first.
            raise NonRetryableError(
                f"integrity violation on {constraint or 'unknown constraint'}: "
                f"{exc.orig}"
            ) from exc

        # Anything else is unexpected. Re-raised so it takes the ordinary retry
        # path and ends in the dead letter queue if it persists — observable
        # either way, which is the point.
        raise


async def process_outbox() -> int:

    outbox_worker_heartbeat.set(now_ts())

    start = time.perf_counter()

    async with AsyncSessionLocal() as db:

        processed = await process_batch(db)

    outbox_processing_time_seconds.observe(time.perf_counter() - start)
    
    return processed