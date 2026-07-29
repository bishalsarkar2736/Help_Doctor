import logging
import json
from datetime import datetime
from app.core.time import UTC
from app.try_except.context import (
    request_id_ctx,
    user_id_ctx,
    clinic_id_ctx,
)
from app.core.correlation import (
    correlation_id_ctx,
)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "correlation_id": correlation_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "clinic_id": clinic_id_ctx.get(),
        }

        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in standard_attrs
        }

        log_record.update(extras)
        

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
