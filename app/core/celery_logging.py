"""Structured logging for the Celery worker and beat processes.

The API calls setup_logging() in create_app(), so its logs are JSON. The Celery
processes called nothing, so theirs were plain text in Celery's own format.
Everything this project added for diagnosis was therefore invisible to
structured log tooling on the side that produces it:

    outbox_integrity_error          the foreign-key-vs-duplicate distinction
    duplicate_notification_skipped  expected idempotent conflicts
    notification_purge_complete     retention counts
    mark_no_show_task_completed     how many appointments were marked
    push_notification_failed        delivery failures with their tracebacks

All of it is emitted by worker processes. A query for `outbox_integrity_error`
against a JSON log store returned nothing, not because it never fired but
because the process writing it was not speaking the same language.

WHY THE SIGNAL RATHER THAN A CALL
Celery configures logging itself when a worker boots, and hijacks the root
logger to do it. Calling setup_logging() at import time would be undone. Celery
documents exactly one way to take that over: connect the `setup_logging` signal.
Connecting it tells Celery to leave logging alone entirely, so ours is the
configuration that survives.

Connected for side effects on import, the same way app/core/celery_metrics.py
attaches its signals and for the same reason — celery.py imports both so a
worker gets them without every task module remembering to.

worker_process_init as well: with the prefork pool each child is a fresh
process, and a handler installed only in the parent is not inherited through
the fork on every platform. Installing it per child is idempotent — setup_logging
replaces root.handlers rather than appending, so this cannot stack duplicates.
"""

import logging

from celery.signals import setup_logging as celery_setup_logging
from celery.signals import worker_process_init

from app.config import get_settings
from app.try_except.logging import setup_logging

logger = logging.getLogger(__name__)


@celery_setup_logging.connect
def configure_celery_logging(**_kwargs):
    """Take over Celery's logging with the API's JSON configuration.

    Connecting this signal at all is what stops Celery configuring logging
    itself; the body then installs ours. Returning nothing is correct — Celery
    only checks whether a receiver is attached.
    """
    setup_logging(get_settings().DEBUG)


@worker_process_init.connect
def configure_forked_child_logging(**_kwargs):
    """Re-install in each prefork child.

    Idempotent: setup_logging assigns root.handlers rather than appending.
    """
    setup_logging(get_settings().DEBUG)
