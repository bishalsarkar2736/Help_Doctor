"""Mark appointments nobody turned up to.

mark_no_show_appointments has existed, with a test, since before this file —
and nothing ran it. It was absent from beat_schedule and from every container
in docker-compose, so in production CONFIRMED appointments stayed CONFIRMED
forever, however long ago they were due. That is the opposite of dead code:
working, tested logic that was never invoked.

This module only schedules it. The grace period, the cutoff arithmetic and the
transition itself all stay in the service, untouched.

WHY THIS COMMITS AND THE OLD SCRIPT DID NOT
The service ends with flush(), not commit() — deliberately, so a caller can
compose it into a larger unit of work. scripts/mark_no_show.py never supplied
that commit: it opened a session, called the service, printed a count and let
the context manager close, which rolls back. It reported marking appointments
and marked none. Running it was the only way to find that out, and nobody was
running it.

ONE SCHEDULER, MANY WORKERS
docker-compose runs a single celery_beat container. Beat decides when; workers
execute. That is this project's existing answer to duplicate execution and no
extra lock is added on top of it.

If a second beat did somehow run, the work is still safe rather than doubled:
the query selects only CONFIRMED rows, and transition_appointment_locked
version-checks each one, so a concurrent duplicate raises StaleDataError
instead of transitioning an appointment twice. Idempotence is a property of the
query, not of the schedule.
"""

import logging

from app.core.celery import celery_app
from app.db.postgres import AsyncSessionLocal
from app.services.appointment_no_show_service import mark_no_show_appointments
from app.task.base import run_async

logger = logging.getLogger(__name__)


async def mark_no_show_job() -> int:
    """Run one pass, and commit it."""
    async with AsyncSessionLocal() as db:
        try:
            marked = await mark_no_show_appointments(db)

            # The service flushes; without this the transaction is discarded on
            # exit and the count returned describes work that never landed.
            await db.commit()

            return marked
        except Exception:
            await db.rollback()
            raise


async def run_and_log() -> int:
    """One pass, with the account of it.

    Separate from the Celery task so it can be awaited directly. The task body
    itself cannot be: @run_async calls asyncio.run(), which raises inside an
    already-running loop, so a test would have to drive Celery synchronously
    from a thread to observe any of this.
    """
    logger.info("mark_no_show_task_started")

    try:
        marked = await mark_no_show_job()
    except Exception:
        # exception() rather than error(): the traceback is the whole value of
        # this line, since nobody is watching a job that runs every 5 minutes.
        logger.exception("mark_no_show_task_failed")
        raise

    logger.info(
        "mark_no_show_task_completed",
        extra={"appointments_marked": marked},
    )

    return marked


@celery_app.task(
    name="app.tasks.appointment_no_show.mark_no_show_task",
    bind=True,
    # The global task_time_limit is 30s, set for the short jobs it was written
    # for. This one transitions a row at a time and the first run after
    # deployment clears a backlog of every overdue appointment ever, which is
    # unbounded by anything except how long the job has been switched off.
    # Bounded below the five-minute interval so a slow run cannot overlap the
    # next one.
    time_limit=270,
    soft_time_limit=240,
    # No autoretry. The next run is four minutes away and selects exactly the
    # same rows, because an appointment that failed to transition is still
    # CONFIRMED and still overdue. Retrying would only duplicate that.
    max_retries=0,
)
@run_async
async def mark_no_show_task(self):
    return await run_and_log()
