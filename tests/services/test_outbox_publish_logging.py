"""publish_event writes an outbox row and one structured log line — nothing else.

WHAT IT USED TO DO
Six print() calls and traceback.print_stack(limit=12), unconditionally, on every
publish. Since every appointment, payment, prescription, notification and reminder
event comes through this one function — including a reminder job that runs every
minute — that was a stack dump per event, on stdout, outside the JSON formatter
the API and workers use.

WHAT THESE TESTS PIN
That nothing is written to stdout or stderr, that the structured record survives
intact, that the publishing behaviour itself is untouched, and that an exception
still propagates rather than being caught and logged. The last one matters: the
function has never had an exception handler, and "make errors observable" is not a
licence to add one here — the caller owns the transaction and already reports the
failure.

The source-level guards are AST-based. A text search for "print(" would trip over
the module docstring, which describes what was removed on purpose.
"""

import ast
import io
import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.outbox_event import OutboxEvent
from app.services import outbox_service
from app.services.outbox_service import publish_event
from app.try_except.logging import JsonFormatter

SOURCE = Path(outbox_service.__file__)


class _Recorded:
    """The module's own logger, captured through the real JsonFormatter.

    Not caplog, and not capsys. Two things get in the way:

    setup_logging assigns root.handlers, and the app factory calls it, so a
    root-level capture is reconfigured out from under the test.

    alembic/env.py used to call fileConfig() with its default
    disable_existing_loggers=True, which set disabled = True on every logger
    imported before the migration ran — which, under conftest, is all of them. It
    now passes False, so this no longer bites. The state is still normalised here
    rather than assumed, because a logger's level and disabled flag are global and
    another test could leave either one set.
    """

    def __init__(self, name: str = "app.services.outbox_service"):
        self.logger = logging.getLogger(name)
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())

    def __enter__(self):
        self._level = self.logger.level
        self._disabled = self.logger.disabled

        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)
        self.logger.disabled = False

        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self._level)
        self.logger.disabled = self._disabled

        return False

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    def records(self) -> list[dict]:
        return [
            json.loads(line)
            for line in self.text.splitlines()
            if line.strip()
        ]


def _payload(**overrides) -> dict:
    payload = {
        "event_type": "APPOINTMENT_CONFIRMED",
        "schema_version": 1,
        "aggregate_type": "appointment",
        "aggregate_id": 7,
        "appointment_id": 7,
        "user_id": 42,
        "clinic_id": 3,
        "correlation_id": "corr-abc-123",
    }
    payload.update(overrides)

    return payload


# ---------------------------------------------------------------------------
# Nothing reaches stdout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishing_writes_nothing_to_stdout(db, capsys):
    capsys.readouterr()

    await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    captured = capsys.readouterr()

    assert captured.out == "", f"publish_event wrote to stdout: {captured.out!r}"
    assert captured.err == "", f"publish_event wrote to stderr: {captured.err!r}"


@pytest.mark.asyncio
async def test_publishing_writes_no_stack_trace(db, capsys):
    """The specific thing that was there: a stack dump per event."""
    capsys.readouterr()

    await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    emitted = capsys.readouterr()
    everything = emitted.out + emitted.err

    assert "File \"" not in everything
    assert "publish_event" not in everything
    assert "=" * 20 not in everything


@pytest.mark.asyncio
async def test_many_publishes_stay_silent(db, capsys):
    """The reminder job publishes one of these per due appointment, once a
    minute. Silence has to hold in a loop, not just once."""
    capsys.readouterr()

    for index in range(5):
        await publish_event(
            db=db,
            event_type="APPOINTMENT_CONFIRMED",
            payload=_payload(aggregate_id=index, appointment_id=index),
        )

    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# The publishing behaviour is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exactly_one_outbox_event_is_created(db):
    before = len(
        (await db.execute(select(OutboxEvent))).scalars().all()
    )

    await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    after = (await db.execute(select(OutboxEvent))).scalars().all()

    assert len(after) == before + 1


@pytest.mark.asyncio
async def test_the_event_type_is_stored_verbatim(db):
    event = await publish_event(
        db=db, event_type="PRESCRIPTION_REVISED", payload=_payload()
    )

    stored = await db.scalar(
        select(OutboxEvent.event_type).where(OutboxEvent.id == event.id)
    )

    assert stored == "PRESCRIPTION_REVISED"


@pytest.mark.asyncio
async def test_the_payload_is_stored_unchanged(db):
    payload = _payload()

    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=payload
    )

    stored = await db.scalar(
        select(OutboxEvent.payload).where(OutboxEvent.id == event.id)
    )

    assert stored == payload


@pytest.mark.asyncio
async def test_the_recipient_and_tenant_survive_the_round_trip(db):
    """user_id and clinic_id are ordinary payload keys, so this is really a check
    that nothing filters the payload on its way in."""
    event = await publish_event(
        db=db,
        event_type="APPOINTMENT_CONFIRMED",
        payload=_payload(user_id=99, clinic_id=17),
    )

    stored = await db.scalar(
        select(OutboxEvent.payload).where(OutboxEvent.id == event.id)
    )

    assert stored["user_id"] == 99
    assert stored["clinic_id"] == 17


@pytest.mark.asyncio
async def test_the_correlation_id_is_lifted_onto_the_row(db):
    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    stored = await db.scalar(
        select(OutboxEvent.correlation_id).where(OutboxEvent.id == event.id)
    )

    assert stored == "corr-abc-123"


@pytest.mark.asyncio
async def test_an_event_without_a_correlation_id_still_publishes(db):
    payload = _payload()
    del payload["correlation_id"]

    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=payload
    )

    assert event.id is not None
    assert event.correlation_id is None


@pytest.mark.asyncio
async def test_the_id_is_available_immediately(db):
    """The flush is what makes this true, and callers rely on it — the reminder
    job and the notification receipts both use the id straight away."""
    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    assert event.id is not None


@pytest.mark.asyncio
async def test_publishing_does_not_commit(db):
    """Transaction behaviour: the row belongs to the caller's transaction, so a
    rollback must take it with it."""
    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    event_id = event.id

    await db.rollback()

    surviving = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.id == event_id)
    )

    assert surviving is None, "publish_event committed on its own"


# ---------------------------------------------------------------------------
# The structured record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_structured_record_is_emitted(db):
    """Through the real JsonFormatter — see _Recorded for why not caplog."""
    with _Recorded() as recorded:
        event = await publish_event(
            db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
        )

    records = recorded.records()

    assert records, "no structured record was emitted"

    record = records[-1]

    assert record["message"] == "outbox_event_created"
    assert record["event_type"] == "APPOINTMENT_CONFIRMED"
    assert record["event_id"] == str(event.id)
    assert record["correlation_id"] == "corr-abc-123"
    assert "appointment_id" in record["payload_keys"]


@pytest.mark.asyncio
async def test_the_structured_record_carries_no_payload_values(db):
    """Keys, not values. The payload can hold a cancellation reason or a refund
    amount, and a log line is a much less private place than the row."""
    with _Recorded() as recorded:
        await publish_event(
            db=db,
            event_type="APPOINTMENT_CANCELLED",
            payload=_payload(reason="suspected tuberculosis"),
        )

    emitted = recorded.text

    assert "tuberculosis" not in emitted
    assert "reason" in emitted  # the key is there; the value is not


# ---------------------------------------------------------------------------
# Exceptions still propagate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_publishing_failure_propagates(db, monkeypatch):
    """Requirement: do not silently swallow.

    The failure is injected at the flush, which is where a real one occurs — a
    constraint violation or a lost connection.
    """
    async def _boom():
        raise RuntimeError("connection lost")

    monkeypatch.setattr(db, "flush", _boom)

    with pytest.raises(RuntimeError, match="connection lost"):
        await publish_event(
            db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
        )


@pytest.mark.asyncio
async def test_a_publishing_failure_is_not_logged_here(db, monkeypatch, capsys):
    """Deliberately NOT logged in this function, and pinned so that "make errors
    observable" does not later turn into a handler here.

    publish_event has never caught anything. The caller owns the transaction and
    reports the failure; a handler here would either swallow it or double-report
    it. What must hold is that the error escapes and nothing is printed on the way
    out.
    """
    async def _boom():
        raise RuntimeError("connection lost")

    monkeypatch.setattr(db, "flush", _boom)

    capsys.readouterr()

    with pytest.raises(RuntimeError):
        await publish_event(
            db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
        )

    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


def test_the_function_has_no_exception_handler():
    """The structural form of the test above."""
    tree = ast.parse(SOURCE.read_text())

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "publish_event"
    )

    handlers = [
        node for node in ast.walk(function)
        if isinstance(node, ast.ExceptHandler)
    ]

    assert not handlers, (
        "publish_event now handles exceptions; it never did, and the caller's "
        "transaction is where a publish failure belongs"
    )


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------


def test_no_print_remains_in_the_module():
    """Parsed, not grepped: the module docstring names print() on purpose."""
    tree = ast.parse(SOURCE.read_text())

    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]

    assert not offenders, f"print() at line(s) {offenders}"


def test_the_traceback_module_is_not_used():
    tree = ast.parse(SOURCE.read_text())

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "traceback" not in imported

    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "print_stack" not in called
    assert "print_exc" not in called
    assert "format_stack" not in called


def test_no_second_logging_configuration_is_introduced():
    """One logger, obtained the same way every other module obtains it.

    No basicConfig, no dictConfig, no setup_logging, no handler attached here —
    those belong to the application and worker entrypoints, and a module that
    configures logging on import fights whichever one ran first.
    """
    tree = ast.parse(SOURCE.read_text())

    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for forbidden in (
        "basicConfig", "dictConfig", "fileConfig", "setup_logging",
        "addHandler", "setFormatter", "removeHandler",
    ):
        assert forbidden not in called, (
            f"outbox_service configures logging ({forbidden})"
        )


def test_the_module_still_uses_the_standard_module_logger():
    tree = ast.parse(SOURCE.read_text())

    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "logger"
            for target in node.targets
        )
    ]

    assert len(assignments) == 1

    call = assignments[0].value

    assert isinstance(call, ast.Call)
    assert call.func.attr == "getLogger"
    assert isinstance(call.args[0], ast.Name)
    assert call.args[0].id == "__name__"


def test_the_publishing_statements_are_exactly_these():
    """A tight pin on the body, so scaffolding cannot creep back in unnoticed.

    Five statements: build the row, add it, flush it, log it, return it.
    """
    tree = ast.parse(SOURCE.read_text())

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "publish_event"
    )

    body = [
        statement for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]

    assert len(body) == 5, (
        f"publish_event has {len(body)} statements, expected 5"
    )

    assert isinstance(body[-1], ast.Return)
