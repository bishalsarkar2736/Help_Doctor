from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "helpdoctor",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.task.appointment_reminders",
        "app.task.slot_generation",
        "app.task.payment_reconciliation",
        "app.task.notification_tasks",
        "app.task.phi_access_retention",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # reliability settings
    task_acks_late=True,
    # With acks_late, a task is only acked after it completes. If a worker is
    # hard-killed (SIGKILL / OOM) mid-task, this requeues it instead of losing
    # it — the two must be set together.
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,

    # task limits
    task_time_limit=30,
    task_soft_time_limit=20,

    # Pinned here rather than as a --concurrency CLI flag, so it holds however
    # the worker is launched — compose, systemd, a bare shell, or the command
    # printed in README/OPERATIONS/DEPLOYMENT.
    #
    # Celery otherwise forks one child per CPU, and each child opens its own DB
    # pool. On a 16-core host that is 16 x (DB_POOL_SIZE + DB_MAX_OVERFLOW)
    # connections from this service alone, which overruns Postgres. The work is
    # I/O-bound, so extra children buy little. See DB_POOL_SIZE in config.py.
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
)

# Importing for the side effect of connecting Celery's signals — without this
# the worker exports nothing and background jobs fail silently.
from app.core import celery_metrics  # noqa: E402,F401


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

    # Nightly at 03:20 UTC — off the hour, so it does not start in the same
    # second as the hourly slot generation and contend for the DB pool.
    # Deliberately not more frequent: nothing here is time-critical, and each
    # run rewrites index pages on the busiest-write table in the system.
    "phi-access-log-retention": {
        "task": "app.tasks.phi_access_retention.phi_access_log_purge_task",
        "schedule": crontab(hour=3, minute=20),
    },

}