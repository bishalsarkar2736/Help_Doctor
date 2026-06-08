import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.db.postgres import AsyncSessionLocal
from app.models.outbox_event import OutboxEvent
from app.core.time import UTC
from sqlalchemy.exc import IntegrityError
from app.services.notification_service import notify_user

logger = logging.getLogger(__name__)


# =========================
# CELERY ENTRY POINT
# =========================
@celery_app.task(name="process_outbox_events")
def process_outbox_events():
    asyncio.run(_run())


# =========================
# MAIN LOOP
# =========================
async def _run():
    async with AsyncSessionLocal(expire_on_commit=False) as db:

        result = await db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                (
                    (OutboxEvent.next_retry_at == None)
                    | (OutboxEvent.next_retry_at <= datetime.now(UTC))
                )
            )
            .order_by(OutboxEvent.created_at)
            .limit(50)
            .with_for_update(skip_locked=True)  # ✅ CRITICAL
        )

        events = result.scalars().all()

        for event in events:
            # =========================
            # BASIC IDEMPOTENCY GUARD
            # =========================
            if event.status != "pending":
                continue

            try:

                event.status = "processing"
                event.processing_started_at = datetime.now(UTC)
                await db.flush()

                await handle_event(db, event)

                event.status = "processed"
                event.processed_at = datetime.now(UTC)
                event.processing_started_at = None
                event.next_retry_at = None
                event.last_error = None

                await db.flush()  # durability

            except Exception as e:
                logger.exception(
                    "outbox_processing_failed",
                    extra={
                        "event_id": str(event.id),
                        "error_type": type(e).__name__,
                        "retry_count": event.retry_count,
                    }
                )

                event.retry_count += 1
                event.last_error = str(e)[:500]
                event.processing_started_at = None

                if event.retry_count >= event.max_retries:
                    event.status = "failed"
                    event.failed_at = datetime.now(UTC)
                else:
                    event.status = "pending"
                    delay = 2 ** event.retry_count
                    event.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

                await db.flush()

        await db.commit()


# =========================
# EVENT DISPATCHER
# =========================
async def handle_event(db: AsyncSession, event: OutboxEvent):

    payload = event.payload or {}
    schema_version = payload.get("schema_version", 0)

    # =========================
    # PAYLOAD VALIDATION
    # =========================
    if not payload or "user_id" not in payload:
        logger.error(
            "invalid_outbox_payload",
            extra={
                "event_id": str(event.id),
                "payload": payload,
            }
        )
        raise ValueError("invalid outbox payload")

    logger.info(
        "processing_outbox_event",
        extra={
            "event_id": str(event.id),
            "event_type": event.event_type,
            "schema_version": schema_version,
        },
    )

    # =========================
    # PAYMENT SUCCESS
    # =========================
    if event.event_type == "payment_success":

        try:
            await notify_user(
                db=db,
                user_id=payload["user_id"],
                title="Payment Successful",
                message="Your appointment has been confirmed.",
                appointment_id=payload.get("appointment_id"),
                event_id=event.id,
            )

        except IntegrityError:
            logger.warning(
                "duplicate_notification_skipped",
                extra={"event_id": str(event.id)},
            )

    # =========================
    # STATUS CHANGE
    # =========================
    elif event.event_type == "APPOINTMENT_STATUS_CHANGED":

        try:
            await notify_user(
                db=db,
                user_id=payload["patient_id"],
                title="Appointment Updated",
                message=f"Your appointment status changed to {payload['new_status']}.",
                appointment_id=payload["appointment_id"],
                event_id=event.id,
            )

        except IntegrityError:
            logger.warning(
                "duplicate_notification_skipped",
                extra={"event_id": str(event.id)},
            )

    # =========================
    # CANCELLED
    # =========================
    elif event.event_type == "APPOINTMENT_CANCELLED":

        raw = payload.get("cancelled_by")

        # backward compatibility
        if isinstance(raw, dict):
            role = raw.get("role", "UNKNOWN")
        else:
            role = raw or "UNKNOWN"

        if role == "PATIENT":
            message = "The patient has cancelled the appointment."
        elif role == "DOCTOR":
            message = "The doctor has cancelled your appointment."
        elif role == "ADMIN":
            message = "The appointment was cancelled by admin."
        else:
            message = "Your appointment has been cancelled."

        try:
            await notify_user(
                db=db,
                user_id=payload["user_id"],
                title="Appointment Cancelled",
                message=message,
                appointment_id=payload["appointment_id"],
                event_id=event.id,
            )

        except IntegrityError:
            logger.warning(
                "duplicate_notification_skipped",
                extra={"event_id": str(event.id)},
            )

    # =========================
    # RESCHEDULED
    # =========================
    elif event.event_type == "APPOINTMENT_RESCHEDULED":

        try:
            await notify_user(
                db=db,
                user_id=payload["user_id"],
                title="Appointment Rescheduled",
                message="Your appointment has been rescheduled by the doctor.",
                appointment_id=payload["appointment_id"],
                event_id=event.id,
            )

        except IntegrityError:
            logger.warning(
                "duplicate_notification_skipped",
                extra={"event_id": str(event.id)},
            )

    # =========================
    # RESCHEDULE REQUEST
    # =========================
    elif event.event_type == "APPOINTMENT_RESCHEDULE_REQUEST":
        
        try:
            await notify_user(
                db=db,
                user_id=payload["user_id"],
                title="Reschedule Request",
                message="A patient requested to reschedule an appointment.",
                appointment_id=payload["appointment_id"],
                event_id=event.id,
            )
        except IntegrityError:
            logger.warning(
                "duplicate_notification_skipped",
                extra={"event_id": str(event.id)},
            )

    # =========================
    # UNKNOWN EVENT
    # =========================
    else:
        logger.warning(
            "unhandled_outbox_event",
            extra={
                "event_type": event.event_type,
                "event_id": str(event.id),
                "payload": payload,
            },
        )