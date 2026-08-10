"""The notification-preferences contract, and WhatsApp's place in it.

whatsapp_enabled has been in the model and read by the delivery handler for as
long as the column has existed, while being absent from both the response schema
and the update schema. The effect was not a cosmetic gap: the preference
defaults to False — WhatsApp is the one opt-in channel — so nothing could be
delivered on it by anyone, whatever the server was configured to do, because
there was no way for a patient to say yes.

This is the first coverage the ROUTE has had — tests/services/
test_notification_preferences.py exercises the service beneath it, and neither
file mentioned whatsapp_enabled. So this pins the whole HTTP contract rather
than only the new field: email, push and in-app behaviour is asserted here too,
because "adding WhatsApp" is only correct if it changed nothing else.

The file name carries an _api suffix because pytest collects these directories
without __init__.py, so two modules with the same basename collide.

WHAT ISOLATES THE CHANNELS
An omitted field in the PATCH body arrives as None and is skipped, so a request
that mentions only WhatsApp cannot disturb the other three. That is asserted
per-channel below rather than trusted, since it is the property most likely to
break the day someone replaces the update service with a bulk assignment.

WHOSE PREFERENCES
The subject is always the authenticated caller: the row is looked up by
current_user.id and the update schema has no user_id field to override it. So
one user addressing another's preferences is not refused, it is unrepresentable
— which is the stronger property, and is asserted both ways.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.time import utc_now
from app.models.appointment import AppointmentStatus
from app.models.notification_preference import NotificationPreference
from app.schemas.notification_preference import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)
from app.services.event_handlers import notification_whatsapp_handler

ENDPOINT = "/notification-preferences/"

TEMPLATE = "helpdoctor_prescription_issued"


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_exposes_whatsapp_enabled(client, auth_patient):
    response = await client.get(ENDPOINT, headers=auth_patient["headers"])

    assert response.status_code == 200
    assert "whatsapp_enabled" in response.json()


@pytest.mark.asyncio
async def test_whatsapp_defaults_to_off(client, auth_patient):
    """The one channel that starts disabled.

    Email, push and in-app are all on by default; WhatsApp is a message to a
    personal phone number through a third party, and the default should not
    assume consent to that.
    """
    response = await client.get(ENDPOINT, headers=auth_patient["headers"])

    assert response.json()["whatsapp_enabled"] is False


@pytest.mark.asyncio
async def test_get_still_exposes_the_other_three(client, auth_patient):
    """Nothing was displaced by adding a fourth channel."""
    body = (await client.get(ENDPOINT, headers=auth_patient["headers"])).json()

    assert body["email_enabled"] is True
    assert body["push_enabled"] is True
    assert body["realtime_enabled"] is True


@pytest.mark.asyncio
async def test_get_creates_the_row_with_whatsapp_off(
    db, client, auth_patient
):
    """A first read materialises the preferences, so the default has to be
    right in the row and not only in the response."""
    await client.get(ENDPOINT, headers=auth_patient["headers"])

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert prefs is not None
    assert prefs.whatsapp_enabled is False


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_user_can_enable_whatsapp(db, client, auth_patient):
    response = await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    assert response.status_code == 200
    assert response.json()["whatsapp_enabled"] is True

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert prefs.whatsapp_enabled is True, "the change was not persisted"


@pytest.mark.asyncio
async def test_a_user_can_disable_whatsapp_again(db, client, auth_patient):
    """Opting in must be reversible, and reversible from the enabled state
    rather than only from the default."""
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    response = await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": False},
        headers=auth_patient["headers"],
    )

    assert response.json()["whatsapp_enabled"] is False

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert prefs.whatsapp_enabled is False


@pytest.mark.asyncio
async def test_the_change_survives_a_reread(client, auth_patient):
    """Asserted through a second request, because the PATCH response could be
    right while the commit is not."""
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    body = (await client.get(ENDPOINT, headers=auth_patient["headers"])).json()

    assert body["whatsapp_enabled"] is True


# ---------------------------------------------------------------------------
# One channel at a time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "untouched", ["email_enabled", "push_enabled", "realtime_enabled"]
)
async def test_enabling_whatsapp_leaves_the_other_channels_alone(
    db, client, auth_patient, untouched
):
    """A PATCH that mentions only WhatsApp must not reset an omitted field.

    Parametrised over all three rather than written once, because a bulk
    assignment would break them all and a reordering might break only one.
    """
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert getattr(prefs, untouched) is True, (
        f"{untouched} was changed by a WhatsApp-only PATCH"
    )


@pytest.mark.asyncio
async def test_a_channel_turned_off_stays_off_when_whatsapp_changes(
    db, client, auth_patient
):
    """The inverse, and the one that matters: the defaults are all True, so a
    test that only ever sees True cannot tell "preserved" from "reset"."""
    await client.patch(
        ENDPOINT,
        json={"email_enabled": False, "push_enabled": False},
        headers=auth_patient["headers"],
    )

    response = await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    body = response.json()

    assert body["whatsapp_enabled"] is True
    assert body["email_enabled"] is False, "email was re-enabled"
    assert body["push_enabled"] is False, "push was re-enabled"

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert (prefs.email_enabled, prefs.push_enabled) == (False, False)


@pytest.mark.asyncio
async def test_the_other_channels_still_toggle(db, client, auth_patient):
    """Existing behaviour, pinned. This endpoint had no tests before, so there
    was nothing to catch a regression in email or push."""
    response = await client.patch(
        ENDPOINT,
        json={
            "email_enabled": False,
            "push_enabled": False,
            "realtime_enabled": False,
        },
        headers=auth_patient["headers"],
    )

    body = response.json()

    assert body["email_enabled"] is False
    assert body["push_enabled"] is False
    assert body["realtime_enabled"] is False

    # And WhatsApp was not dragged along by a change to the others.
    assert body["whatsapp_enabled"] is False


@pytest.mark.asyncio
async def test_an_empty_patch_changes_nothing(db, client, auth_patient):
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    body = (
        await client.patch(
            ENDPOINT, json={}, headers=auth_patient["headers"]
        )
    ).json()

    assert body == {
        "email_enabled": True,
        "whatsapp_enabled": True,
        "push_enabled": True,
        "realtime_enabled": True,
    }


# ---------------------------------------------------------------------------
# Whose preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_user_cannot_change_anothers_preferences(
    db, client, auth_patient, auth_another_patient
):
    """Attempted the only way the API allows — by asking for it in the body."""
    victim = auth_another_patient["user"]

    await client.patch(
        ENDPOINT,
        json={
            "whatsapp_enabled": True,
            "user_id": victim.id,
            "id": victim.id,
        },
        headers=auth_patient["headers"],
    )

    victim_prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == victim.id
        )
    )

    # Either untouched or never created; what must not have happened is the
    # caller's opt-in landing on someone else's row.
    assert victim_prefs is None or victim_prefs.whatsapp_enabled is False

    caller_prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == auth_patient["user"].id
        )
    )

    assert caller_prefs.whatsapp_enabled is True, (
        "the caller's own preference should still have been applied"
    )


@pytest.mark.asyncio
async def test_the_update_schema_cannot_name_a_user():
    """The structural reason the test above passes.

    Pinned separately because "the field is ignored" and "the field does not
    exist" fail differently: adding user_id to the schema would silently make
    the request above meaningful.
    """
    assert "user_id" not in NotificationPreferenceUpdate.model_fields
    assert "user_id" not in NotificationPreferenceResponse.model_fields


@pytest.mark.asyncio
async def test_two_users_hold_independent_preferences(
    client, auth_patient, auth_another_patient
):
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    other = await client.get(
        ENDPOINT, headers=auth_another_patient["headers"]
    )

    assert other.json()["whatsapp_enabled"] is False


@pytest.mark.asyncio
async def test_an_anonymous_caller_is_refused(client):
    assert (await client.get(ENDPOINT)).status_code in (401, 403)
    assert (
        await client.patch(ENDPOINT, json={"whatsapp_enabled": True})
    ).status_code in (401, 403)


# ---------------------------------------------------------------------------
# The preference reaches delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def whatsapp_channel_on(monkeypatch):
    settings = get_settings()

    monkeypatch.setattr(settings, "WHATSAPP_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(
        settings, "WHATSAPP_TEMPLATE_PRESCRIPTION_ISSUED", TEMPLATE
    )

    return settings


@pytest.fixture
def whatsapp_sent(monkeypatch):
    messages = []

    async def _capture(**kwargs):
        messages.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService,
        "send_template",
        _capture,
    )

    return messages


async def _send_for(db, patient_user, appointment):
    """Run the WhatsApp handler for one patient, reading whatever preference the
    API has left behind."""
    from types import SimpleNamespace

    await notification_whatsapp_handler.handle_notification_whatsapp(
        db=db,
        validated=SimpleNamespace(
            patient_id=patient_user.id,
            appointment_id=appointment.id,
        ),
        event_id=uuid.uuid4(),
        event_type="PRESCRIPTION_ISSUED",
        user_field="patient_id",
    )


@pytest.mark.asyncio
async def test_the_handler_sends_once_the_user_has_opted_in(
    db, client, auth_patient, doctor, appointment_factory,
    whatsapp_channel_on, whatsapp_sent,
):
    """The point of the milestone, end to end: the toggle is what decides
    whether a message goes out.

    Without this the API change would be a field that round-trips through JSON
    and reaches nothing.
    """
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=doctor.id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=utc_now() + timedelta(hours=3),
    )

    await _send_for(db, auth_patient["user"], appointment)

    assert whatsapp_sent == [], "sent while the user had not opted in"

    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )

    await _send_for(db, auth_patient["user"], appointment)

    assert len(whatsapp_sent) == 1, "opting in did not reach delivery"
    assert whatsapp_sent[0]["template_name"] == TEMPLATE


@pytest.mark.asyncio
async def test_the_handler_stops_when_the_user_opts_out(
    db, client, auth_patient, doctor, appointment_factory,
    whatsapp_channel_on, whatsapp_sent,
):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=doctor.id,
        status=AppointmentStatus.CONFIRMED,
        scheduled_at=utc_now() + timedelta(hours=4),
    )

    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": True},
        headers=auth_patient["headers"],
    )
    await client.patch(
        ENDPOINT,
        json={"whatsapp_enabled": False},
        headers=auth_patient["headers"],
    )

    await _send_for(db, auth_patient["user"], appointment)

    assert whatsapp_sent == []


# ---------------------------------------------------------------------------
# No credentials in the contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_response_carries_no_provider_configuration(
    client, auth_patient
):
    """The preference says whether the user wants WhatsApp, and nothing about
    how the server talks to Meta. A token or a phone number id in a user-facing
    response is a leak, and the toggle is a tempting place to put one."""
    settings = get_settings()

    body = (await client.get(ENDPOINT, headers=auth_patient["headers"])).json()

    assert set(body) == {
        "email_enabled",
        "whatsapp_enabled",
        "push_enabled",
        "realtime_enabled",
    }

    serialised = str(body)

    assert settings.WHATSAPP_ACCESS_TOKEN not in serialised
    assert settings.WHATSAPP_PHONE_NUMBER_ID not in serialised
