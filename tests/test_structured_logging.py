import json
import logging

from app.try_except.logging import JsonFormatter
from app.try_except.context import user_id_ctx, clinic_id_ctx


def _format(msg: str) -> dict:
    record = logging.LogRecord("test", logging.INFO, "f.py", 1, msg, None, None)
    return json.loads(JsonFormatter().format(record))


def test_log_includes_user_and_clinic_from_context():
    user_id_ctx.set(42)
    clinic_id_ctx.set(7)
    out = _format("hello")
    assert out["user_id"] == 42
    assert out["clinic_id"] == 7
    assert out["message"] == "hello"
    # request/correlation ids are always present keys too.
    assert "request_id" in out
    assert "correlation_id" in out


def test_log_context_is_null_when_unset():
    user_id_ctx.set(None)
    clinic_id_ctx.set(None)
    out = _format("hi")
    assert out["user_id"] is None
    assert out["clinic_id"] is None
