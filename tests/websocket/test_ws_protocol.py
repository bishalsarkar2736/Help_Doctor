from unittest.mock import AsyncMock, patch

from app.models.user import UserRole


def build_user(role=UserRole.PATIENT, clinic_id=1):

    # clinic_id is a real column on User, and the connect handler reads it to
    # pick which clinic's dashboard channel an admin joins. The stub carried
    # only id and role, so it described a user that cannot exist and the
    # handler raised AttributeError rather than failing on anything real.
    return type(
        "User",
        (),
        {
            "id": 1,
            "role": role,
            "clinic_id": clinic_id,
        },
    )()


def websocket_patches(role=UserRole.PATIENT):

    return patch(
        "app.websocket.routes.decode_token_from_ws",
        new_callable=AsyncMock,
    ), patch(
        "app.services.presence_service.set_user_online",
        new_callable=AsyncMock,
    ), patch(
        "app.services.presence_service.set_user_offline",
        new_callable=AsyncMock,
    ), patch(
        "app.services.presence_broadcast_service.broadcast_presence",
        new_callable=AsyncMock,
    ), build_user(role)


def test_ws_ping_pong(ws_client):

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches()

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.send_json({
                "event": "ping",
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "pong"


def test_ws_unknown_event(ws_client):

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches()

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.send_json({
                "event": "invalid_event",
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "error"
            assert response["message"] == "unknown_event"


def test_ws_subscribe(ws_client):

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
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.receive_json()

            # An arbitrary name is no longer a channel anyone may join:
            # subscription is authorized per resource. This admin's own
            # clinic dashboard is the channel they are entitled to, and it
            # is decidable without the stub existing in the database.
            channel = f"admin_dashboard:{user.clinic_id}"

            websocket.send_json({
                "event": "subscribe",
                "channel": channel,
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "subscribed"
            assert response["channel"] == channel


def test_ws_unsubscribe(ws_client):

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
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.receive_json()

            websocket.send_json({
                "event": "unsubscribe",
                "channel": "test_channel",
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "unsubscribed"
            assert response["channel"] == "test_channel"


def test_ws_notification_delivered(ws_client):

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches()

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,

        patch(
            "app.websocket.routes.mark_notification_delivered",
            new_callable=AsyncMock,
        ) as mock_delivered,
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.send_json({
                "event": "notification_delivered",
                "notification_id": 123,
            })

            response = websocket.receive_json()

            assert response["event"] == "notification_delivered_ack"

            mock_delivered.assert_awaited_once_with(
                notification_id=123,
                user_id=1,
            )


def test_ws_notification_seen(ws_client):

    (
        auth_patch,
        online_patch,
        offline_patch,
        presence_patch,
        user,
    ) = websocket_patches()

    with (
        auth_patch as mock_auth,
        online_patch,
        offline_patch,
        presence_patch,

        patch(
            "app.websocket.routes.mark_notifications_seen",
            new_callable=AsyncMock,
        ) as mock_seen,
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.send_json({
                "event": "notification_seen",
                "notification_ids": [1, 2, 3],
            })

            response = websocket.receive_json()

            assert response["event"] == "notification_seen_ack"

            mock_seen.assert_awaited_once_with(
                notification_ids=[1, 2, 3],
                user_id=1,
            )

def test_ws_subscribe_to_another_clinics_channel_is_refused(ws_client):
    """The protocol half of the authorization fix.

    The unit tests in test_channel_authorization.py decide the rule; this
    asserts the handler actually consults it and refuses over the wire rather
    than joining the channel and reporting success.
    """

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
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.receive_json()

            websocket.send_json({
                "event": "subscribe",
                "channel": f"admin_dashboard:{user.clinic_id + 1}",
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "error"
            assert response["message"] == "subscribe_not_allowed"


def test_ws_subscribe_to_an_arbitrary_channel_is_refused(ws_client):
    """A name that corresponds to no resource is not a channel."""

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
    ):

        mock_auth.return_value = user

        with ws_client.websocket_connect("/ws") as websocket:

            websocket.receive_json()

            websocket.send_json({
                "event": "subscribe",
                "channel": "test_channel",
            })

            response = websocket.receive_json()

            assert response["event"] == "error"
            assert response["message"] == "subscribe_not_allowed"
