import pytest
from unittest.mock import AsyncMock, patch

from app.services.event_handlers.prescription_email_handler import (
    handle_prescription_issued_email,
)

from app.models.notification import Notification

from app.models.notification_preference import (
    NotificationPreference,
)

from app.schemas.event import PrescriptionIssuedEvent


@pytest.mark.asyncio
async def test_email_success(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            email_enabled=True,
        )
    )

    notification = Notification(
        user_id=issued_prescription.patient_id,
        title="Prescription",
        message="Issued",
        category="PRESCRIPTION",
        event_id=issued_prescription_event.id,
    )

    db.add(notification)

    await db.commit()

    validated = PrescriptionIssuedEvent.model_validate(
        issued_prescription_event.payload
    )

    with (
        patch(
            "app.services.event_handlers.prescription_email_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_email_handler.send_prescription_email",
            new=AsyncMock(),
        ),
    ):

        await handle_prescription_issued_email(
            db=db,
            validated=validated,
            event_id=issued_prescription_event.id,
        )

    await db.commit()

    await db.refresh(notification)

    assert notification.email_delivered_at is not None
    assert notification.email_failed_at is None



@pytest.mark.asyncio
async def test_email_failure(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            email_enabled=True,
        )
    )

    notification = Notification(
        user_id=issued_prescription.patient_id,
        title="Prescription",
        message="Issued",
        category="PRESCRIPTION",
        event_id=issued_prescription_event.id,
    )

    db.add(notification)

    await db.commit()

    validated = PrescriptionIssuedEvent.model_validate(
        issued_prescription_event.payload
    )

    with (
        patch(
            "app.services.event_handlers.prescription_email_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_email_handler.send_prescription_email",
            new=AsyncMock(
                side_effect=Exception("SMTP down")
            ),
        ),
    ):

        with pytest.raises(Exception):

            await handle_prescription_issued_email(
                db=db,
                validated=validated,
                event_id=issued_prescription_event.id,
            )

    await db.commit()

    await db.refresh(notification)

    assert notification.email_failed_at is not None
    assert notification.email_error == "SMTP down"


@pytest.mark.asyncio
async def test_email_preference_disabled(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            email_enabled=False,
        )
    )

    notification = Notification(
        user_id=issued_prescription.patient_id,
        title="Prescription",
        message="Issued",
        category="PRESCRIPTION",
        event_id=issued_prescription_event.id,
    )

    db.add(notification)

    await db.commit()

    validated = PrescriptionIssuedEvent.model_validate(
        issued_prescription_event.payload
    )

    sender = AsyncMock()

    with (
        patch(
            "app.services.event_handlers.prescription_email_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_email_handler.send_prescription_email",
            new=sender,
        ),
    ):

        await handle_prescription_issued_email(
            db=db,
            validated=validated,
            event_id=issued_prescription_event.id,
        )

    sender.assert_not_awaited()

    await db.refresh(notification)

    assert notification.email_delivered_at is None
    assert notification.email_failed_at is None