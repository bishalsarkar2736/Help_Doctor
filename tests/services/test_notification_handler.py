from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy import select

from app.core.time import UTC
from app.models.notification import (
    Notification,
    NotificationCategory,
)
from app.schemas.event import PaymentRefundedEvent
from app.schemas.event_metadata import EventActor
from app.services.event_handlers.notification_handler import (
    handle_notification_event,
)
from tests.helpers.payment import (
    create_success_payment,
)
from tests.helpers.outbox import (
    create_outbox_event,
)


@pytest.mark.asyncio
async def test_payment_refunded_notification_created(
    db,
    default_clinic,
):
    
    payment = await create_success_payment(
        db,
        default_clinic,
    )

    event = PaymentRefundedEvent(
        event_type="PAYMENT_REFUNDED",
        user_id=payment.patient_id,
        appointment_id=payment.appointment_id,
        payment_id=payment.id,
        refund_transaction_id="refund-123",
        refunded_amount="100",
        occurred_at=datetime.now(UTC).isoformat(),
        aggregate_type="payment",
        aggregate_id=payment.id,
        actor=EventActor(
            id=1,
            role="doctor",
        ),
    )

    outbox = await create_outbox_event(
        db=db,
        event=event,
    )

    await handle_notification_event(
        db=db,
        validated=event,
        event_id=outbox.id,
        event_type=event.event_type,
    )

    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == event.user_id)
    )

    notifications = result.scalars().all()

    assert len(notifications) == 1

    notification = notifications[0]

    assert notification.title == "Payment Refunded"

    assert (
        notification.message
        == "Your payment of ৳100 has been refunded"
    )

    assert (
        notification.category
        == NotificationCategory.PAYMENT
    )

    assert notification.user_id == event.user_id

    assert (
        notification.related_appointment_id
        == event.appointment_id
    )