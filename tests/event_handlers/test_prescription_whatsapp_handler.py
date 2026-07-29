import pytest
from unittest.mock import AsyncMock, patch

from app.services.event_handlers.prescription_whatsapp_handler import (
    handle_prescription_issued_whatsapp,
)

from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.schemas.event import PrescriptionIssuedEvent


@pytest.mark.asyncio
async def test_whatsapp_success(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            whatsapp_enabled=True,
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
            "app.services.event_handlers.prescription_whatsapp_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_whatsapp_handler.send_prescription_whatsapp",
            new=AsyncMock(),
        ),
    ):

        await handle_prescription_issued_whatsapp(
            db=db,
            validated=validated,
            event_id=issued_prescription_event.id,
        )

    await db.commit()

    await db.refresh(notification)

    assert notification.whatsapp_delivered_at is not None



@pytest.mark.asyncio
async def test_whatsapp_failure(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            whatsapp_enabled=True,
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
            "app.services.event_handlers.prescription_whatsapp_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_whatsapp_handler.send_prescription_whatsapp",
            new=AsyncMock(
                side_effect=Exception("Twilio error")
            ),
        ),
    ):

        with pytest.raises(Exception):

            await handle_prescription_issued_whatsapp(
                db=db,
                validated=validated,
                event_id=issued_prescription_event.id,
            )

    await db.commit()

    await db.refresh(notification)

    assert notification.whatsapp_failed_at is not None
    assert notification.whatsapp_error == "Twilio error"


@pytest.mark.asyncio
async def test_whatsapp_preference_disabled(
    db,
    issued_prescription,
    issued_prescription_event,
):
    db.add(
        NotificationPreference(
            user_id=issued_prescription.patient_id,
            whatsapp_enabled=False,
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
            "app.services.event_handlers.prescription_whatsapp_handler.generate_prescription_pdf",
            return_value=b"PDF",
        ),
        patch(
            "app.services.event_handlers.prescription_whatsapp_handler.send_prescription_whatsapp",
            new=sender,
        ),
    ):

        await handle_prescription_issued_whatsapp(
            db=db,
            validated=validated,
            event_id=issued_prescription_event.id,
        )

    sender.assert_not_awaited()

    await db.refresh(notification)

    assert notification.whatsapp_delivered_at is None
    assert notification.whatsapp_failed_at is None