"""A failure receipt must never replace the failure it is recording.

WHAT WENT WRONG
Every channel handler ends the same way:

    except Exception as exc:
        await mark_whatsapp_failed(db=db, ...)   # another DB write
        await db.commit()
        raise

When the original exception is a database error, Postgres has already ABORTED
the transaction. That receipt write is therefore the second statement on a dead
transaction, and SQLAlchemy raises PendingRollbackError from inside the except
block — which propagates INSTEAD of the original error.

The outbox worker then stores that as last_error, so the row says

    "This Session's transaction has been rolled back due to a previous
     exception during flush"

and the actual cause — a foreign key violation naming the constraint — is gone.
96 dead-lettered events in this database carry that message, and the audit that
found them could only identify the real cause by correlating deleted users
against event payloads.

WHAT THESE TESTS PIN
1. The original exception survives. Bookkeeping is best-effort; the diagnosis
   is not.
2. The receipt write is attempted first and only repaired if it fails, so the
   ordinary case — a channel failing for a NON-database reason, where the
   transaction is perfectly healthy — still writes and commits a receipt
   against a notification row that is still there. Rolling back first
   unconditionally would discard that row and lose the receipt it points at.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.notification import Notification


async def _poison(db) -> None:
    """Leave the session's transaction aborted, exactly as a constraint
    violation does. Any statement after this raises until it is rolled back."""

    with pytest.raises(Exception):
        await db.execute(text("SELECT 1 / 0"))


# ---------------------------------------------------------------------------
# 1. The original error is preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_receipt_helper_does_not_raise_on_an_aborted_transaction(db):
    """THE CORE PROPERTY.

    The helper is called from inside an `except` block. If it raises, its own
    exception replaces the one being handled — which is how the real cause was
    lost 96 times.
    """
    from app.services.notification_receipt_service import (
        mark_whatsapp_failed,
        record_delivery_failure,
    )

    await _poison(db)

    # Must not raise, whatever state the session is in.
    await record_delivery_failure(
        db,
        mark=mark_whatsapp_failed,
        event_id=None,
        user_id=1,
        error="original failure",
    )


@pytest.mark.asyncio
async def test_the_session_is_usable_after_the_helper_gives_up(db):
    """The worker's own bookkeeping runs next and rolls back first, but leaving
    a poisoned session behind would make any intermediate statement fail for a
    second, unrelated reason."""

    from app.services.notification_receipt_service import (
        mark_email_failed,
        record_delivery_failure,
    )

    await _poison(db)

    await record_delivery_failure(
        db,
        mark=mark_email_failed,
        event_id=None,
        user_id=1,
        error="original failure",
    )

    # A plain read must work again.
    assert await db.scalar(text("SELECT 1")) == 1


@pytest.mark.asyncio
async def test_the_original_exception_propagates_from_a_channel_handler(
    db, monkeypatch
):
    """End to end through a handler's except block.

    The receipt write is forced to fail the way an aborted transaction makes it
    fail. What must reach the caller is the ORIGINAL error, not the bookkeeping
    one.
    """
    from sqlalchemy.exc import PendingRollbackError

    import app.services.notification_receipt_service as receipts

    original = IntegrityError("INSERT ...", {}, Exception("fk violation"))

    async def _exploding_mark(**_kwargs):
        raise PendingRollbackError("can't reconnect until invalid transaction")

    monkeypatch.setattr(receipts, "mark_whatsapp_failed", _exploding_mark)

    async def _channel_that_fails(db):
        try:
            raise original
        except Exception as exc:
            await receipts.record_delivery_failure(
                db,
                mark=receipts.mark_whatsapp_failed,
                event_id=None,
                user_id=1,
                error=str(exc),
            )
            raise

    with pytest.raises(IntegrityError) as seen:
        await _channel_that_fails(db)

    assert seen.value is original, (
        "the bookkeeping exception replaced the original failure"
    )


# ---------------------------------------------------------------------------
# 2. The healthy path is unchanged — the receipt is still written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_receipt_is_still_written_when_the_transaction_is_healthy(
    db, patient_user, appointment_factory, auth_doctor
):
    """The ordinary case: a channel fails for a NON-database reason — the API
    returned 500, the phone number was rejected — and the transaction is fine.

    This is why the fix repairs rather than pre-emptively rolls back: a
    rollback here would discard the notification the receipt is written onto.
    """
    from app.services.notification_receipt_service import (
        mark_whatsapp_failed,
        record_delivery_failure,
    )
    from app.services.notification_service import create_notification
    from app.models.notification import NotificationCategory
    from app.models.outbox_event import OutboxEvent

    from app.models.appointment import AppointmentStatus

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    # notifications.event_id is a real foreign key into outbox_events, so the
    # event has to exist before a notification can point at it.
    event = OutboxEvent(event_type="APPOINTMENT_STATUS_CHANGED", payload={})
    db.add(event)
    await db.flush()
    event_id = event.id

    await create_notification(
        db=db,
        user_id=patient_user.id,
        title="t",
        message="m",
        category=NotificationCategory.APPOINTMENT,
        event_id=event_id,
        appointment_id=appointment.id,
    )
    await db.flush()

    await record_delivery_failure(
        db,
        mark=mark_whatsapp_failed,
        event_id=event_id,
        user_id=patient_user.id,
        error="gateway returned 500",
    )

    row = await db.scalar(
        select(Notification).where(
            Notification.event_id == event_id,
            Notification.user_id == patient_user.id,
        )
    )

    assert row is not None, "the notification was discarded"
    assert row.whatsapp_failed_at is not None, "no receipt was recorded"
    assert "gateway returned 500" in (row.whatsapp_error or "")


# ---------------------------------------------------------------------------
# 3. Every channel uses the same helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "app.services.event_handlers.notification_email_handler",
        "app.services.event_handlers.notification_whatsapp_handler",
        "app.services.event_handlers.prescription_whatsapp_handler",
    ],
)
def test_each_channel_records_its_failure_through_the_helper(module):
    """Structural, because the hazard is a shape rather than a value: a
    `mark_*_failed` called directly from an except block is a DB write on a
    transaction that may already be dead."""

    import ast
    import importlib
    import pathlib

    source = pathlib.Path(importlib.import_module(module).__file__).read_text()
    tree = ast.parse(source)

    direct = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue

        for handler in node.handlers:
            for inner in ast.walk(handler):
                if not isinstance(inner, ast.Call):
                    continue

                name = getattr(inner.func, "id", None) or getattr(
                    inner.func, "attr", None
                )

                if name in {"mark_whatsapp_failed", "mark_email_failed"}:
                    direct.append(f"{module}:{inner.lineno} {name}")

    assert not direct, (
        "failure receipt written directly from an except block, so an aborted "
        f"transaction will replace the original error: {direct}"
    )
