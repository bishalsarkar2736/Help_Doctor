"""Worker diagnostics are readable, and notification history is not collateral.

Two production-safety gaps, unrelated except that both made a real problem
invisible.

The API configured JSON logging in create_app(); the Celery worker and the
standalone outbox worker configured plain text or nothing. Every diagnostic this
project added for the notification path — outbox_integrity_error,
duplicate_notification_skipped, notification_purge_complete,
push_notification_failed — is emitted by a worker process, so querying a
structured log store for any of them returned nothing. Not because they never
fired, but because the side producing them was not speaking the same language.

And notifications.event_id referenced outbox_events with ON DELETE CASCADE.
Nothing deletes outbox events today, so nothing has been lost — but notification
retention establishes the pattern, and the first outbox retention job written to
match it would have deleted notification history as a side effect, silently.
"""

import json
import logging

import pytest
from sqlalchemy import text

from app.models.notification import Notification
from app.try_except.logging import JsonFormatter, setup_logging


@pytest.fixture
async def deliverable_notification(db):
    """One outbox event with one notification recorded from it."""
    import uuid

    from app.core.time import utc_now
    from app.models.notification import NotificationCategory
    from app.models.outbox_event import OutboxEvent
    from app.models.user import User, UserRole

    user = User(
        email="cascade-user@example.com", full_name="Cascade User",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CONFIRMED",
        payload={}, status="processed",
    )
    db.add(event)
    await db.flush()

    notification = Notification(
        user_id=user.id, title="t", message="m",
        category=NotificationCategory.APPOINTMENT, event_id=event.id,
        created_at=utc_now(),
    )
    db.add(notification)
    await db.flush()

    return {"event": event, "notification": notification, "user": user}


@pytest.fixture
async def orphan_outbox_event(db):
    """An outbox event that produced no notification."""
    import uuid

    from app.models.outbox_event import OutboxEvent

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CONFIRMED",
        payload={}, status="processed",
    )
    db.add(event)
    await db.flush()

    return event


# ---------------------------------------------------------------------------
# 1. Worker logging is structured
# ---------------------------------------------------------------------------


def test_the_standalone_outbox_worker_installs_json_logging():
    """It used logging.basicConfig(level=INFO) — plain text.

    Asserted by reading the module rather than importing it: importing runs the
    module body, which reconfigures the root logger and would leave the rest of
    the suite logging as the worker does.
    """
    from pathlib import Path

    source = (
        Path(__file__).parent.parent.parent
        / "app" / "workers" / "run_outbox_worker.py"
    ).read_text()

    assert "setup_logging(" in source, (
        "the outbox worker does not install the shared logging configuration"
    )
    assert "logging.basicConfig" not in source, (
        "basicConfig still overrides the structured configuration"
    )


def test_celery_connects_the_setup_logging_signal():
    """Celery configures logging itself and hijacks the root logger when it
    boots. Connecting its setup_logging signal is the documented way to take
    that over — a plain call at import time would be undone."""
    from celery.signals import setup_logging as celery_setup_logging

    import app.core.celery_logging  # noqa: F401

    receivers = [
        getattr(r(), "__name__", None) if callable(r) else None
        for _, r in celery_setup_logging.receivers
    ]

    assert "configure_celery_logging" in receivers, (
        "nothing is connected to Celery's setup_logging signal, so Celery will "
        "configure logging itself and ours will be discarded"
    )


def test_celery_reinstalls_logging_in_forked_children():
    """The prefork pool runs each task in a child process; a handler installed
    only in the parent is not reliably inherited."""
    from celery.signals import worker_process_init

    import app.core.celery_logging  # noqa: F401

    receivers = [
        getattr(r(), "__name__", None) if callable(r) else None
        for _, r in worker_process_init.receivers
    ]

    assert "configure_forked_child_logging" in receivers


def test_celery_logging_is_wired_into_the_app():
    """Imported for side effects from celery.py, the same way celery_metrics is.
    Without that import the signals are never connected."""
    from pathlib import Path

    source = (
        Path(__file__).parent.parent.parent / "app" / "core" / "celery.py"
    ).read_text()

    assert "celery_logging" in source, (
        "celery.py does not import celery_logging, so the signals never connect"
    )


def test_setup_logging_produces_parseable_json(capsys):
    """The shared configuration, exercised rather than assumed: whatever the
    worker installs has to emit something a log store can parse."""
    previous = logging.getLogger().handlers[:]

    try:
        setup_logging(False)

        logging.getLogger("app.test.worker").info(
            "outbox_integrity_error",
            extra={"event_id": "abc", "sqlstate": "23503"},
        )

        captured = capsys.readouterr()
        line = (captured.err or captured.out).strip().splitlines()[-1]

        record = json.loads(line)

        assert record["message"] == "outbox_integrity_error"
        assert record["level"] == "INFO"
        assert record["logger"] == "app.test.worker"

    finally:
        logging.getLogger().handlers = previous


@pytest.mark.parametrize(
    "message",
    [
        # One per diagnostic the workers emit, so a formatter change that drops
        # `extra` is caught for all of them rather than for whichever one a
        # single test happened to pick.
        "outbox_integrity_error",
        "duplicate_notification_skipped",
        "notification_purge_complete",
        "push_notification_failed",
        "mark_no_show_task_completed",
    ],
)
def test_worker_diagnostics_survive_json_formatting(message):
    """Structured logging is only useful if the structured part survives.

    Each of these is logged with `extra`, and it is the extra that carries the
    event id, the count and the sqlstate — the fields anybody querying the log
    would filter on.
    """
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="app.workers.test", level=logging.INFO, pathname=__file__,
        lineno=1, msg=message, args=(), exc_info=None,
    )
    record.deleted = 7
    record.event_id = "e-1"

    parsed = json.loads(formatter.format(record))

    assert parsed["message"] == message
    assert parsed["deleted"] == 7
    assert parsed["event_id"] == "e-1"


def test_a_traceback_survives_json_formatting():
    """push_notification_failed and mark_no_show_task_failed use
    logger.exception; the traceback is the whole value of those lines."""
    formatter = JsonFormatter()

    try:
        raise RuntimeError("device unreachable")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="app.workers.test", level=logging.ERROR, pathname=__file__,
            lineno=1, msg="push_notification_failed", args=(),
            exc_info=sys.exc_info(),
        )

    parsed = json.loads(formatter.format(record))

    assert "device unreachable" in parsed["exception"]


# ---------------------------------------------------------------------------
# 2. Notification history is not collateral damage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_foreign_key_restricts_rather_than_cascades(db):
    """Read from the database, not the model: what protects the rows is the
    constraint that exists, not the annotation describing it."""
    definition = await db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'fk_notifications_event_id'"
        )
    )

    assert "ON DELETE RESTRICT" in definition, (
        f"notifications.event_id is not protected: {definition}"
    )
    assert "ON DELETE CASCADE" not in definition


@pytest.mark.asyncio
async def test_deleting_an_outbox_event_with_notifications_is_refused(
    db, deliverable_notification
):
    """The protection, exercised.

    Under CASCADE this DELETE succeeded and took the notification with it. Now
    it raises, which is the point: a future outbox purge fails visibly instead
    of quietly removing history.
    """
    from sqlalchemy.exc import IntegrityError

    event_id = deliverable_notification["event"].id

    with pytest.raises(IntegrityError):
        await db.execute(
            text("DELETE FROM outbox_events WHERE id = :i"), {"i": event_id}
        )
        await db.flush()

    await db.rollback()


@pytest.mark.asyncio
async def test_the_notification_survives_the_refused_delete(
    db, deliverable_notification
):
    """Belt and braces: the refusal is only useful if the row is still there
    afterwards."""
    from sqlalchemy.exc import IntegrityError

    event_id = deliverable_notification["event"].id
    notification_id = deliverable_notification["notification"].id

    # Committed first so the rollback below undoes only the refused DELETE. The
    # db fixture shares one savepoint, so rolling back without this would
    # discard the fixture's own rows and the survival check would pass or fail
    # for the wrong reason.
    await db.commit()

    try:
        await db.execute(
            text("DELETE FROM outbox_events WHERE id = :i"), {"i": event_id}
        )
        await db.flush()
    except IntegrityError:
        await db.rollback()

    survived = await db.scalar(
        text("SELECT count(*) FROM notifications WHERE id = :i"),
        {"i": notification_id},
    )

    assert survived == 1


@pytest.mark.asyncio
async def test_an_outbox_event_without_notifications_can_still_be_deleted(
    db, orphan_outbox_event
):
    """RESTRICT refuses only what it must.

    A future retention job can still purge events that produced no
    notification, which is most of them — the protection is targeted, not a
    blanket freeze on the table.
    """
    await db.execute(
        text("DELETE FROM outbox_events WHERE id = :i"),
        {"i": orphan_outbox_event.id},
    )
    await db.flush()

    remaining = await db.scalar(
        text("SELECT count(*) FROM outbox_events WHERE id = :i"),
        {"i": orphan_outbox_event.id},
    )

    assert remaining == 0


def test_nothing_in_the_codebase_deletes_outbox_events():
    """The reason RESTRICT changes no current behaviour.

    If a delete is ever added, this fails and whoever added it has to decide
    what happens to the notifications rather than finding out later.
    """
    import re
    from pathlib import Path

    root = Path(__file__).parent.parent.parent

    offenders = []

    for path in list((root / "app").rglob("*.py")) + list(
        (root / "scripts").rglob("*.py")
    ):
        source = path.read_text()

        for match in re.finditer(
            r"(delete\(\s*OutboxEvent|DELETE\s+FROM\s+outbox_events)",
            source,
            re.IGNORECASE,
        ):
            line = source[: match.start()].count("\n") + 1
            stripped = source.splitlines()[line - 1].strip()

            if stripped.startswith("#"):
                continue

            offenders.append(f"{path.relative_to(root)}:{line}")

    assert not offenders, (
        f"outbox events are now deleted somewhere: {offenders}. RESTRICT will "
        f"refuse any of these that has notifications — decide deliberately "
        f"what should happen to that history."
    )


@pytest.mark.asyncio
async def test_notification_retention_is_unaffected(db, deliverable_notification):
    """Notification retention deletes notifications, not outbox events, so the
    constraint does not stand in its way."""
    from datetime import timedelta

    from app.services.notification_retention_service import (
        purge_expired_notifications,
    )

    notification = deliverable_notification["notification"]
    notification.created_at = notification.created_at - timedelta(days=400)
    await db.flush()

    deleted = await purge_expired_notifications(
        db=db, retention_days=365, batch_size=100, max_batches=10
    )

    assert deleted == 1

    assert await db.scalar(
        text("SELECT count(*) FROM outbox_events WHERE id = :i"),
        {"i": deliverable_notification["event"].id},
    ) == 1, "retention removed the outbox event as well"
