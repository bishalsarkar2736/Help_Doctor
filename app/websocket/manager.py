from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.db.redis import get_redis

from app.core.ws_metrics import (
    active_websocket_connections,
    websocket_messages_total,
    websocket_errors_total,
)

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.tracing import (
    inject_trace_attributes,
)


logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

CHANNEL_NAME = "ws_notifications"

SEND_TIMEOUT = 5
MAX_CONNECTIONS_PER_USER = 5
HEARTBEAT_TIMEOUT = 30


class ConnectionManager:

    def __init__(self):

        # user_id -> multiple websocket connections
        self.active_connections: dict[int, set[WebSocket]] = defaultdict(set)
        
        # channel -> websockets
        self.channels: dict[str, set[WebSocket]] = defaultdict(set)

        self.lock = asyncio.Lock()

    # =====================================================
    # CONNECTION MANAGEMENT
    # =====================================================

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket,
    ):

        #await websocket.accept()

        async with self.lock:

            sockets = self.active_connections[user_id]

            # Prevent abuse / browser tab explosion
            if len(sockets) >= MAX_CONNECTIONS_PER_USER:

                logger.warning(
                    "ws_connection_limit_exceeded",
                    extra={
                        "user_id": user_id,
                        "limit": MAX_CONNECTIONS_PER_USER,
                    },
                )

                await websocket.close(code=1008)

                return False
            
            await websocket.accept()

            sockets.add(websocket)

            active_websocket_connections.inc()

        logger.info(
            "ws_connected",
            extra={
                "user_id": user_id,
                "total_connections": self.total_connections,
            },
        )

        return True
    

    # async def disconnect(
    #     self,
    #     user_id: int,
    #     websocket: WebSocket,
    # ):

    #     async with self.lock:

    #         sockets = self.active_connections.get(user_id)

    #         if not sockets:
    #             return

    #         sockets.discard(websocket)

    #         active_websocket_connections.dec()

    #         # cleanup empty sets
    #         if not sockets:
    #             self.active_connections.pop(user_id, None)

    #     logger.info(
    #         "ws_disconnected",
    #         extra={
    #             "user_id": user_id,
    #             "total_connections": self.total_connections,
    #         },
    #     )

    async def disconnect(
        self,
        user_id: int,
        websocket: WebSocket,
    ):

        async with self.lock:

            sockets = self.active_connections.get(user_id)

            if sockets:

                if websocket in sockets:

                    sockets.discard(websocket)

                    active_websocket_connections.dec()

                # cleanup empty socket sets
                if not sockets:
                    self.active_connections.pop(user_id, None)

            # cleanup channel subscriptions
            empty_channels = []

            for channel, subscribers in self.channels.items():

                subscribers.discard(websocket)

                if not subscribers:
                    empty_channels.append(channel)

            # remove empty channels
            for channel in empty_channels:
                self.channels.pop(channel, None)

        logger.info(
            "ws_disconnected",
            extra={
                "user_id": user_id,
                "total_connections": self.total_connections,
            },
        )

    @property
    def total_connections(self) -> int:

        return sum(
            len(sockets)
            for sockets in self.active_connections.values()
        )
    

    async def subscribe(
        self,
        channel: str,
        websocket: WebSocket,
    ):

        async with self.lock:

            self.channels[channel].add(
                websocket
            )


    async def unsubscribe(
        self,
        channel: str,
        websocket: WebSocket,
    ):

        async with self.lock:

            sockets = self.channels.get(
                channel
            )

            if not sockets:
                return

            sockets.discard(websocket)

            if not sockets:
                self.channels.pop(
                    channel,
                    None,
                )

    # =====================================================
    # REDIS PUB/SUB PUBLISHER
    # =====================================================

    async def notify_user(
        self,
        user_id: int,
        message: str | dict,
        appointment_id: int | None = None,
    ):
        """
        Publish websocket event through Redis Pub/Sub.

        Supports:
        - multiple FastAPI workers
        - multiple containers
        - horizontal scaling
        """

        with tracer.start_as_current_span(
            "notify_user"
        ) as span:

            span.set_attribute(
                "user_id",
                user_id,
            )

            span.set_attribute(
                "appointment_id",
                appointment_id or 0,
            )

            try:

                if isinstance(message, dict):

                    payload = message.copy()

                    payload.setdefault(
                        "message",
                        None,
                    )

                    payload.setdefault(
                        "appointment_id",
                        appointment_id,
                    )

                

                else:

                    payload = {
                        "message": message,
                        "appointment_id": appointment_id,
                    }

                payload.setdefault(
                    "event",
                    "notification",
                )

                payload.setdefault(
                    "data",
                    {},
                )

                event_name = payload.get(
                        "event",
                        "unknown",
                    )

                span.set_attribute(
                    "event",
                    event_name,
                )

                correlation_id = payload.get(
                    "correlation_id",
                    "",
                )

                span.set_attribute(
                    "correlation_id",
                    correlation_id,
                )

                # internal routing key
                payload["user_id"] = user_id

                redis = await get_redis()

                await redis.publish(
                    CHANNEL_NAME,
                    json.dumps(payload),
                )

                span.set_status(
                        Status(StatusCode.OK)
                    )
                
            except Exception as e:

                span.record_exception(e)

                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        str(e),
                    )
                )

                raise

    # =====================================================
    # LOCAL DELIVERY
    # =====================================================

    async def send_local(
        self,
        user_id: int,
        data: Any,
    ):
        """
        Deliver websocket message to locally connected clients.

        Includes:
        - multi-tab support
        - backpressure protection
        - stale socket cleanup
        """

        async with self.lock:

            sockets = list(
                self.active_connections.get(
                    user_id,
                    set(),
                )
            )

        if not sockets:
            return

        stale_connections = []

        for websocket in sockets:

            try:

                with tracer.start_as_current_span(
                    "websocket_send"
                ) as span:
                    
                    inject_trace_attributes(
                        user_id=user_id,
                        appointment_id=data.get("appointment_id")
                        if isinstance(data, dict)
                        else None,
                    )
                    
                    event_name = (
                        data.get("event", "unknown")
                        if isinstance(data, dict)
                        else "unknown"
                    )

                    span.set_attribute(
                        "user_id",
                        user_id,
                    )

                    span.set_attribute(
                        "event",
                        event_name,
                    )

                    span.set_attribute(
                        "connection_count",
                        len(sockets),
                    )

                    span.set_attribute(
                        "send_timeout_seconds",
                        SEND_TIMEOUT,
                    )

                    # Backpressure protection
                    await asyncio.wait_for(
                        websocket.send_json(data),
                        timeout=SEND_TIMEOUT,
                    )

                    span.set_status(
                        Status(StatusCode.OK)
                    )

                websocket_messages_total.inc()

                

            except Exception as e:

                websocket_errors_total.inc()

                span.record_exception(e)

                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        str(e),
                    )
                )

                logger.warning(
                    "ws_send_failed",
                    extra={
                        "user_id": user_id,
                        "error": str(e),
                    },
                )

                stale_connections.append(websocket)

        # cleanup dead sockets
        for websocket in stale_connections:

            await self.disconnect(
                user_id,
                websocket,
            )

    
    async def broadcast_channel(
        self,
        channel: str,
        data: dict,
    ):

        async with self.lock:

            sockets = list(
                self.channels.get(
                    channel,
                    set(),
                )
            )

        if not sockets:
            return

        stale_connections = []

        for websocket in sockets:

            try:

                await asyncio.wait_for(
                    websocket.send_json(data),
                    timeout=SEND_TIMEOUT,
                )

            except Exception:

                stale_connections.append(
                    websocket
                )

        for websocket in stale_connections:

            await self.unsubscribe(
                channel,
                websocket,
            )


manager = ConnectionManager()