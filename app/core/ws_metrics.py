from prometheus_client import Gauge, Counter


active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Current active websocket connections",
)

websocket_messages_total = Counter(
    "websocket_messages_total",
    "Total websocket messages",
)

websocket_errors_total = Counter(
    "websocket_errors_total",
    "Total websocket errors",
)