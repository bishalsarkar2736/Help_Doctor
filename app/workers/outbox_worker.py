import logging
from datetime import datetime, timedelta
import time
from app.core.time import UTC
import sqlalchemy as sa
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.postgres import AsyncSessionLocal
from app.models.outbox_event import OutboxEvent
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
            OutboxEvent.status == "processing",
            OutboxEvent.failed_at.is_(None),
            OutboxEvent.processing_started_at.is_not(None),
            OutboxEvent.processing_started_at < timeout_threshold,
        )
        .values(
            status="pending",
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
            OutboxEvent.status == "pending",
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
            OutboxEvent.status == "pending",
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

        try:
            event.status = "processing"
            event.processing_started_at = now
            await db.flush()

            logger.info(
                "processing_event",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "retry_count": event.retry_count,
                    "correlation_id": payload.get("correlation_id"),
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

                    print("PROCESSING EVENT:", event.event_type)
                    print("EVENT PAYLOAD:", event.payload)

                    try:

                        await handle_event(
                            db, 
                            event,
                        )
                    except Exception as e:

                        print("HANDLE_EVENT ERROR:", repr(e))
                        raise

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

            event.status = "processed"
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
            logger.error(
                "outbox_non_retryable_error",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "error": str(exc),
                    "payload": event.payload,
                    "correlation_id": payload.get("correlation_id"),
                },
            )

            event.retry_count += 1
            event.status = "failed"
            event.failed_at = now
            event.last_error = str(exc)[:500]
            event.processing_started_at = None
            event.next_retry_at = None

            dlq_batch.append(
                DeadLetterEvent(
                    original_event_id=event.id,
                    event_type=event.event_type,
                    payload=event.payload,
                    retry_count=event.retry_count,
                    max_retries=event.max_retries,
                    error_message=str(exc)[:500],
                )
            )

            outbox_dead_letter_total.inc()
            processed_since_commit += 1
            await db.flush()

        except Exception as exc:
            logger.exception(
                "outbox_event_failed",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "correlation_id": payload.get("correlation_id"),
                },
            )

            event.retry_count += 1
            event.last_error = str(exc)[:500]
            event.processing_started_at = None

            outbox_event_failures_total.inc()

            if event.retry_count >= event.max_retries:

                event.status = "failed"
                event.failed_at = now
                event.next_retry_at = None

                dlq_batch.append(
                    DeadLetterEvent(
                        original_event_id=event.id,
                        event_type=event.event_type,
                        payload=event.payload,
                        retry_count=event.retry_count,
                        max_retries=event.max_retries,
                        error_message=str(exc)[:500],
                    )
                )

                outbox_dead_letter_total.inc()

                logger.critical(
                    "outbox_event_dead_letter",
                    extra={
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "retry_count": event.retry_count,
                        "correlation_id": payload.get("correlation_id"),
                    },
                )
            else:
                event.status = "pending"

                event.next_retry_at = now + timedelta(
                    seconds=min(2 ** event.retry_count, 300)
                )

                logger.warning(
                    "outbox_retry_scheduled",
                    extra={
                        "event_id": str(event.id),
                        "retry_count": event.retry_count,
                        "next_retry_at": event.next_retry_at,
                        "correlation_id": payload.get("correlation_id"),
                    },
                )

            processed_since_commit += 1
            await db.flush()

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

        event.status = "processed"
        event.processed_at = datetime.now(UTC)

        return
    
    try:

        validated = schema.model_validate(
            payload
        )

    except Exception as exc:

        logger.error(
            "event_schema_validation_failed",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "payload": payload,
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

    except IntegrityError:
        logger.info(
            "duplicate_notification_skipped",
            extra={
                "event_id": str(event.id),
                "correlation_id": payload.get("correlation_id"),
            },
        )


async def process_outbox() -> int:

    outbox_worker_heartbeat.set(now_ts())

    start = time.perf_counter()

    async with AsyncSessionLocal() as db:

        processed = await process_batch(db)

    outbox_processing_time_seconds.observe(time.perf_counter() - start)
    
    return processed