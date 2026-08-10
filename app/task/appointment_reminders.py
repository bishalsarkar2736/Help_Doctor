from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.postgres import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.core.time import UTC
from app.core.celery import celery_app
from app.core.constants import REMINDER_LEAD_MINUTES
from app.schemas.event import AppointmentReminderEvent
from app.services.domain_event_service import publish_domain_event
from app.task.base import run_async


import logging

logger = logging.getLogger(__name__)

# REMINDER_LEAD_MINUTES — how far ahead of the appointment the reminder goes out —
# is imported from app.core.constants above.
#
# The approved WhatsApp template says "You have an appointment tomorrow", so it
# has to be a day and not an hour; it used to be 60 minutes, which made the
# message wrong about the one fact it stated. It lives in constants because
# appointment confirmation needs the same number to decide whether an appointment
# is already inside the lead time, and the two must not be able to disagree.

# The width of the band BELOW the lead time that still qualifies.
#
# The job selects a band around the 24-hour mark, not everything inside the next
# 24 hours. Selecting "within 24 hours" would be the obvious reading of a
# lead time and it is wrong: an appointment booked for this afternoon is within
# 24 hours, so it would immediately be told it is "tomorrow".
#
# The band also has to be wider than the gap between runs, or an appointment can
# step over it while the worker is busy or restarting and never be reminded at
# all. Beat runs this every 60 seconds, so an hour of tolerance is sixty chances
# to catch each appointment — it survives a worker outage of up to an hour.
#
# Widening it further trades accuracy for resilience: at 23 hours' notice the
# message is still true, so 60 minutes is comfortably inside what "tomorrow" can
# absorb, while 12 hours would not be.
REMINDER_CATCHUP_MINUTES = 60

# unique lock id for this job
REMINDER_JOB_LOCK_ID = 987654321


async def send_appointment_reminders():
    async with AsyncSessionLocal() as db:

        # 🔒 Acquire advisory lock
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": REMINDER_JOB_LOCK_ID},
        )
        locked = result.scalar()

        if not locked:
            # another worker is running this job
            return

        try:
            now = datetime.now(UTC)

            # A band ending at the lead time, so an appointment qualifies once it
            # is between 23 and 24 hours away.
            latest = now + timedelta(minutes=REMINDER_LEAD_MINUTES)

            earliest = latest - timedelta(minutes=REMINDER_CATCHUP_MINUTES)

            stmt = select(Appointment).where(
                Appointment.status == AppointmentStatus.CONFIRMED,
                # The lower bound is nearly a day in the future, so appointments
                # already past are excluded by it. The old query needed an
                # explicit `>= now` for that; this one cannot select them.
                Appointment.scheduled_at >= earliest,
                Appointment.scheduled_at <= latest,
                Appointment.reminder_sent == False,
            )

            result = await db.execute(stmt)
            appointments = result.scalars().all()

            logger.info(
                "reminder_job_scanned",
                extra={"due_appointments": len(appointments)},
            )

            for appointment in appointments:
                # Published through publish_domain_event like every other event
                # in the system. This used to construct an OutboxEvent directly
                # with event_type="appointment.reminder" — a second, informal
                # publishing path whose type matched nothing in EVENT_SCHEMAS, so
                # the worker marked it processed and dropped it on every run.
                await publish_domain_event(
                    db=db,
                    event=AppointmentReminderEvent(
                        event_type="APPOINTMENT_REMINDER",
                        occurred_at=now.isoformat(),
                        aggregate_type="appointment",
                        aggregate_id=appointment.id,
                        # The patient. The reminder is for whoever is attending,
                        # and the recipient is checked against this appointment's
                        # patient_id downstream.
                        user_id=appointment.patient_id,
                        appointment_id=appointment.id,
                    ),
                )

                # Only after the event exists.
                #
                # What actually guarantees the flag cannot outlive a failed
                # publish is the transaction: both writes are in it, and the
                # rollback below discards both together, so the appointment stays
                # due and the next run picks it up. A test proves that, and
                # reordering these two lines does not break it.
                #
                # The order is still deliberate, as defence for the shape this
                # loop is most likely to grow into: a per-appointment try/except
                # that logs one failure and continues with the batch. The moment
                # a failure stops unwinding the transaction, the ordering becomes
                # the only thing standing between a publish error and a reminder
                # consumed forever. Pinned by a source-level test.
                appointment.reminder_sent = True

            await db.commit()  # ✅ commit success

        except SQLAlchemyError:
            # 🔥 CRITICAL: rollback failed transaction.
            #
            # This is also what keeps reminder_sent honest: the flag and the
            # event are written in one transaction, so a failure discards both
            # and every appointment in the batch remains due.
            await db.rollback()
            logger.exception("reminder_job_db_error")
            raise  # let Celery retry

        except Exception:
            # 🔥 catch any unexpected errors
            await db.rollback()
            logger.exception("reminder_job_failed")
            raise

        finally:
            # 🔓 Release advisory lock safely
            try:
                await db.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": REMINDER_JOB_LOCK_ID},
                )
            except Exception:
                # Don't crash the job if unlock fails
                logger.exception(
                    "Failed to release reminder job advisory lock",
                    extra={
                        "lock_id": REMINDER_JOB_LOCK_ID,
                    },
                )

# 🔁 Celery wrapper
@celery_app.task(
    name="app.tasks.notification_reminders.send_appointment_reminders_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
@run_async
async def send_appointment_reminders_task(self):
    """
    Celery wrapper for reminder job.
    """
    await send_appointment_reminders()