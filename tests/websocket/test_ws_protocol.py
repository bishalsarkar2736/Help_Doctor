from unittest.mock import AsyncMock, patch

from app.models.user import UserRole


def build_user(role=UserRole.PATIENT):

    return type(
        "User",
        (),
        {
            "id": 1,
            "role": role,
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

            websocket.send_json({
                "event": "subscribe",
                "channel": "test_channel",
            })

            response = websocket.receive_json()

            assert response["version"] == 1
            assert response["event"] == "subscribed"
            assert response["channel"] == "test_channel"


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