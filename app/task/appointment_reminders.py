from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.postgres import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.outbox_event import OutboxEvent
from app.core.time import UTC
from app.core.celery import celery_app
from app.task.base import run_async

REMINDER_WINDOW_MINUTES = 60

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
            reminder_time = now + timedelta(minutes=REMINDER_WINDOW_MINUTES)

            stmt = select(Appointment).where(
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.scheduled_at >= now,
                Appointment.scheduled_at <= reminder_time,
                Appointment.reminder_sent == False,
            )

            result = await db.execute(stmt)
            appointments = result.scalars().all()

            print(f"[Reminder Job] Found {len(appointments)} appointments")

            for appointment in appointments:
                event = OutboxEvent(
                    event_type="appointment.reminder",
                    payload={
                        "appointment_id": appointment.id,
                        "patient_id": appointment.patient_id,
                        "doctor_id": appointment.doctor_id,
                        "scheduled_at": appointment.scheduled_at.isoformat(),
                    },
                )

                db.add(event)

                # mark as sent
                appointment.reminder_sent = True

            await db.commit()  # ✅ commit success

        except SQLAlchemyError as e:
            # 🔥 CRITICAL: rollback failed transaction
            await db.rollback()
            print("[Reminder Job] DB Error:", e)
            raise  # let Celery retry

        except Exception as e:
            # 🔥 catch any unexpected errors
            await db.rollback()
            print("[Reminder Job] Unexpected Error:", e)
            raise

        finally:
            # 🔓 Release advisory lock safely
            try:
                await db.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": REMINDER_JOB_LOCK_ID},
                )
            except Exception as unlock_error:
                # do NOT crash job if unlock fails
                print("[Reminder Job] Unlock failed:", unlock_error)


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