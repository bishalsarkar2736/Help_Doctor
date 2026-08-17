"""The presence_updates channel exposed every user's connect/disconnect.

WHAT IT WAS
broadcast_presence published {user_id, online} for EVERY user to a single
channel, and may_subscribe granted that channel on role alone:

    if channel == PRESENCE_CHANNEL:
        return user.role == UserRole.ADMIN      # no clinic predicate

Admins were also joined to it directly on connect. So one clinic's admin
received presence transitions for every other tenant's staff and for patients —
the same data GET /users/{user_id}/presence refuses them, reached through a
different door.

WHY IT IS REMOVED RATHER THAN SCOPED
Nothing consumes it. The frontend has two WebSocket hooks — useDoctorQueueSocket
(doctor_queue) and useNotificationSocket (notifications and user_updated) — and
neither handles a presence_update event. An exhaustive search of the client for
presence, presence_update(s), isOnline and is_online returns only the browser's
own window "online"/"offline" listeners. Scoping an unconsumed broadcast would
be building a feature; the smallest honest change is to stop publishing it.

TWO PLACES HAD TO CHANGE, NOT ONE
The connect handler calls manager.subscribe() directly, without consulting
may_subscribe. Denying the channel in the authorization module alone would have
left every admin still receiving presence, because they never asked for it —
they were enrolled.

WHAT IS DELIBERATELY KEPT
set_user_online / set_user_offline still run. They maintain the Redis key that
GET /users/{user_id}/presence reads, and that endpoint — now clinic-scoped — is
the supported way to ask whether someone is online.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user import UserRole
from app.websocket.authorization import may_subscribe

from tests.websocket.test_ws_protocol import build_user, websocket_patches

PRESENCE = "presence_updates"


# ---------------------------------------------------------------------------
# The dynamic subscribe path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_may_not_subscribe_to_presence(db, auth_admin):
    """THE CORE PROPERTY. This channel used to be granted to any ADMIN, with no
    clinic predicate, so it crossed every tenant boundary at once."""

    assert not await may_subscribe(db, auth_admin["user"], PRESENCE)


@pytest.mark.asyncio
async def test_no_role_may_subscribe_to_presence(
    db, auth_admin, auth_receptionist, auth_doctor, auth_patient, auth_super_admin
):
    """Denied for everyone — the channel is no longer published at all."""

    for principal in (
        auth_admin,
        auth_receptionist,
        auth_doctor,
        auth_patient,
        auth_super_admin,
    ):
        assert not await may_subscribe(db, principal["user"], PRESENCE), (
            principal["user"].role
        )


# ---------------------------------------------------------------------------
# The connect path, which bypasses may_subscribe entirely
# ---------------------------------------------------------------------------


def test_an_admin_is_not_enrolled_in_presence_on_connect(ws_client):
    """The connect handler subscribes directly, so denying the dynamic path is
    not enough on its own — an admin never asked for this channel, they were
    put in it."""

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches(UserRole.ADMIN)

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
        patch(
            "app.websocket.routes.manager.subscribe", new_callable=AsyncMock
        ) as mock_subscribe,
    ):
        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:
            websocket.send_json({"event": "ping"})
            websocket.receive_json()

        joined = [call.args[0] for call in mock_subscribe.await_args_list]

        assert PRESENCE not in joined, (
            f"admin was auto-subscribed to the presence channel: {joined}"
        )


def test_connecting_does_not_broadcast_presence(ws_client):
    """Nothing publishes to the channel any more. A broadcast with no legitimate
    subscriber is not harmless — it is the payload waiting for the next time
    somebody re-opens the door."""

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches(UserRole.ADMIN)

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
        patch(
            "app.websocket.routes.manager.broadcast_channel",
            new_callable=AsyncMock,
        ) as mock_broadcast,
    ):
        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:
            websocket.send_json({"event": "ping"})
            websocket.receive_json()

        published = [call.args[0] for call in mock_broadcast.await_args_list]

        assert PRESENCE not in published, (
            f"presence was still published to the channel: {published}"
        )


# ---------------------------------------------------------------------------
# What must keep working
# ---------------------------------------------------------------------------


def test_the_redis_presence_key_is_still_maintained(ws_client):
    """GET /users/{user_id}/presence reads this key. Removing the broadcast must
    not remove the record it was reporting on."""

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches(UserRole.ADMIN)

    # Patched where it is USED, not where it is defined: routes.py imports the
    # name directly, so patching the service module leaves the handler holding
    # the original reference.
    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
        patch(
            "app.websocket.routes.set_user_online", new_callable=AsyncMock
        ) as mock_online,
    ):
        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:
            websocket.send_json({"event": "ping"})
            websocket.receive_json()

        assert mock_online.await_count >= 1, (
            "set_user_online is no longer called, so the presence endpoint has "
            "nothing to read"
        )


@pytest.mark.asyncio
async def test_the_other_channels_are_untouched(
    db, auth_admin, auth_receptionist, auth_doctor, default_clinic
):
    """Only the presence channel changes. The dashboard and queue rules are a
    separate decision and must keep behaving exactly as they did."""

    assert await may_subscribe(
        db, auth_admin["user"], f"admin_dashboard:{default_clinic.id}"
    )
    assert not await may_subscribe(
        db, auth_admin["user"], "admin_dashboard:99999"
    )

    queue = f"doctor_queue:{auth_doctor['doctor'].id}"

    assert await may_subscribe(db, auth_receptionist["user"], queue)
    assert await may_subscribe(db, auth_doctor["user"], queue)


def test_an_admin_still_joins_their_own_clinic_dashboard(ws_client):
    """The connect handler keeps its other subscription."""

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches(UserRole.ADMIN)

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
        patch(
            "app.websocket.routes.manager.subscribe", new_callable=AsyncMock
        ) as mock_subscribe,
    ):
        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:
            websocket.send_json({"event": "ping"})
            websocket.receive_json()

        joined = [call.args[0] for call in mock_subscribe.await_args_list]

        assert f"admin_dashboard:{user.clinic_id}" in joined, joined
