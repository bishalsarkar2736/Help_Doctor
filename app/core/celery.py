from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "helpdoctor",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # reliability settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,

    # task limits
    task_time_limit=30,
    task_soft_time_limit=20,
)

# periodic scheduler
celery_app.conf.beat_schedule = {
    "appointment-reminder-job": {
        "task": "app.tasks.notification_reminders.send_appointment_reminders_task",
        "schedule": 60.0,  # every 60 seconds

     },

      # ✅ ADD HERE
    "generate-doctor-slots": {
        "task": "app.tasks.slot_generation.generate_slots_task",
        "schedule": 3600.0,  # every 1 hour
    },

    "payment-reconciliation-job": {
        "task": "app.tasks.payment_reconciliation.payment_reconciliation_task",
        "schedule": 300.0,
    },

}

celery_app.autodiscover_tasks(["app.tasks"])