"""The last of the debug scaffolding: the worker loop, alembic, and startup.

THREE CHANGES, ONE THEME — nothing that matters goes to stdout, and nothing
sensitive goes into a log at all.

THE WORKER
    print("PROCESSING EVENT:", event.event_type)
    print("EVENT PAYLOAD:", event.payload)
    try:
        await handle_event(db, event)
    except Exception as e:
        print("HANDLE_EVENT ERROR:", repr(e))
        raise

The payload print is the serious one. Event payloads carry a cancellation reason
typed by staff, a refund amount, prescription and patient ids — writing the whole
body to stdout for every event puts all of it in container logs.

The error print was replaced by NOTHING, deliberately, and that needs saying: the
`except` existed only to print and re-raise. Two frames out, the same exception is
already caught by `except Exception as exc: logger.exception("outbox_event_failed")`
with the event id, the type, the correlation id and a full traceback, and recorded
on the span besides. Adding logger.exception at the inner site would have put two
tracebacks in the log for one failure. So the handler is gone and the exception
travels exactly as it did, to the place that already reports it. Tests below pin
that it is logged ONCE, with a traceback, and that retry behaviour is unchanged.

ALEMBIC
fileConfig() defaults to disable_existing_loggers=True, so running a migration set
`disabled = True` on every application logger that already existed. In the test
session — conftest imports the app, then migrates — that silenced application
logging for the whole run.

STARTUP
app/db/postgres.py printed the database name at IMPORT time, before logging was
configured, in every process that imported it. The question survives as a
structured record in the lifespan, where logging exists; the print does not.
"""

import ast
import io
import json
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

import app.db.postgres as postgres_module
import app.main as main_module
from app.models.outbox_event import OutboxEvent
from app.try_except.logging import JsonFormatter
from app.workers import outbox_worker
from app.workers.outbox_worker import process_batch

WORKER_SOURCE = Path(outbox_worker.__file__)
POSTGRES_SOURCE = Path(postgres_module.__file__)
MAIN_SOURCE = Path(main_module.__file__)
ALEMBIC_ENV = Path(__file__).parent.parent.parent / "alembic" / "env.py"

# A payload key whose VALUE must never be logged. Free text, typed by staff, on an
# event that really carries it.
SECRET_REASON = "patient has suspected tuberculosis"


class _Recorded:
    """A logger captured through the real JsonFormatter, into memory.

    Not caplog: setup_logging assigns root.handlers and the app factory calls it,
    so a root-level capture is reconfigured out from under the test. This asserts
    on what the formatter produces for the record, which needs no global state.
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())

    def __enter__(self):
        self._level = self.logger.level
        self._disabled = self.logger.disabled
        self._propagate = self.logger.propagate

        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)
        self.logger.disabled = False
        # Kept off the root handlers so this capture cannot also write to the
        # stderr stream a sibling test is asserting is empty.
        self.logger.propagate = False

        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self._level)
        self.logger.disabled = self._disabled
        self.logger.propagate = self._propagate

        return False

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    def records(self) -> list[dict]:
        return [
            json.loads(line) for line in self.text.splitlines() if line.strip()
        ]

    def named(self, message: str) -> list[dict]:
        return [r for r in self.records() if r.get("message") == message]


async def _pending(db, *, event_type="APPOINTMENT_CANCELLED", **extra) -> OutboxEvent:
    """A PENDING outbox row carrying a payload with something private in it."""
    payload = {
        "event_type": event_type,
        "schema_version": 1,
        "aggregate_type": "appointment",
        "aggregate_id": 1,
        "correlation_id": str(uuid.uuid4()),
        "user_id": 1,
        "appointment_id": 1,
        "reason": SECRET_REASON,
        "cancelled_by": {"id": 1, "role": "DOCTOR"},
    }
    payload.update(extra)

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        payload=payload,
        # LOWERCASE. process_batch selects `status == "pending"`, while several
        # places in the codebase write "PENDING" by hand — an event created with
        # the uppercase spelling is never picked up. Recorded here because a
        # fixture with the wrong case makes every assertion below vacuously pass.
        status="pending",
    )
    db.add(event)
    await db.flush()

    return event


# ---------------------------------------------------------------------------
# The worker writes nothing to stdout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processing_a_batch_writes_nothing_to_stdout(db, capsys, monkeypatch):
    async def _ok(db, event):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await _pending(db)

    capsys.readouterr()

    await process_batch(db)

    captured = capsys.readouterr()

    assert captured.out == "", f"the worker wrote to stdout: {captured.out!r}"


@pytest.mark.asyncio
async def test_a_failing_handler_writes_nothing_to_stdout(db, capsys, monkeypatch):
    """The error print is gone too, and the failure path must stay silent on
    stdout even though it is noisy in the log."""
    async def _fail(db, event):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    await _pending(db)

    capsys.readouterr()

    await process_batch(db)

    captured = capsys.readouterr()

    assert "HANDLE_EVENT ERROR" not in captured.out
    assert "EVENT PAYLOAD" not in captured.out
    assert captured.out == ""


@pytest.mark.asyncio
async def test_the_payload_body_never_reaches_stdout(db, capsys, monkeypatch):
    """The one that matters most: the value, not just the shape."""
    async def _ok(db, event):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await _pending(db)

    capsys.readouterr()

    await process_batch(db)

    everything = "".join(capsys.readouterr())

    assert SECRET_REASON not in everything
    assert "tuberculosis" not in everything


# ---------------------------------------------------------------------------
# What the worker's structured record contains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_processing_record_carries_keys_not_values(db, monkeypatch):
    async def _ok(db, event):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    event = await _pending(db)

    with _Recorded("app.workers.outbox_worker") as recorded:
        await process_batch(db)

    processing = recorded.named("processing_event")

    assert processing, "no processing record was emitted"

    record = processing[-1]

    assert record["event_id"] == str(event.id)
    assert record["event_type"] == "APPOINTMENT_CANCELLED"
    assert "reason" in record["payload_keys"]

    # The key is named; the free text behind it is not.
    assert SECRET_REASON not in recorded.text
    assert "tuberculosis" not in recorded.text


@pytest.mark.asyncio
async def test_there_is_exactly_one_record_per_event_processed(db, monkeypatch):
    """The prints were duplicating a structured record that already existed.

    So the fix added a key to it rather than a second line — worth pinning,
    because "replace the print with a logger call" invites a second record
    carrying the same four fields.
    """
    async def _ok(db, event):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await _pending(db)

    with _Recorded("app.workers.outbox_worker") as recorded:
        await process_batch(db)

    processing = recorded.named("processing_event")

    assert len(processing) == 1, (
        f"{len(processing)} per-event records; expected one"
    )

    # And no second record under any other name describing the same event.
    others = [
        r for r in recorded.records()
        if r.get("message") not in {"processing_event", "outbox_queue_size"}
    ]

    assert others == [], f"extra per-event records: {[r['message'] for r in others]}"


# ---------------------------------------------------------------------------
# A failure is reported once, with a traceback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_handler_failure_is_logged_exactly_once(db, monkeypatch):
    """The reason no logger.exception was added at the inner call site.

    The exception is already reported, with a traceback, by the handler two frames
    out. A second one there would mean two tracebacks per failure — more log, no
    more information.
    """
    async def _fail(db, event):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    await _pending(db)

    with _Recorded("app.workers.outbox_worker") as recorded:
        await process_batch(db)

    failures = [
        record for record in recorded.records()
        if "exception" in record
    ]

    assert len(failures) == 1, (
        f"expected one record with a traceback, got {len(failures)}: "
        f"{[r.get('message') for r in failures]}"
    )

    record = failures[0]

    assert record["message"] == "outbox_event_failed"
    assert record["level"] == "ERROR"
    assert "RuntimeError" in record["exception"]
    assert "handler exploded" in record["exception"]


@pytest.mark.asyncio
async def test_the_failure_record_carries_no_payload_values(db, monkeypatch):
    async def _fail(db, event):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    await _pending(db)

    with _Recorded("app.workers.outbox_worker") as recorded:
        await process_batch(db)

    assert SECRET_REASON not in recorded.text
    assert "tuberculosis" not in recorded.text


# ---------------------------------------------------------------------------
# Retry semantics are untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failure_still_schedules_a_retry(db, monkeypatch):
    """Removing the inner handler must not change what happens after a failure:
    the event stays pending, the counter advances, a retry is scheduled and the
    error is recorded on the row."""
    async def _fail(db, event):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    event = await _pending(db)

    # Committed, as a publisher always does: the worker rolls back before
    # recording a failure, which would otherwise discard this fixture.
    await db.commit()

    await process_batch(db)

    await db.refresh(event)

    assert event.status != "processed"
    assert event.retry_count == 1
    assert event.next_retry_at is not None
    assert "handler exploded" in (event.last_error or "")


@pytest.mark.asyncio
async def test_a_success_still_marks_the_event_processed(db, monkeypatch):
    async def _ok(db, event):
        return None

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    event = await _pending(db)

    await process_batch(db)

    await db.refresh(event)

    assert event.status == "processed"
    assert event.processed_at is not None
    assert event.retry_count == 0
    assert event.last_error is None


@pytest.mark.asyncio
async def test_the_handler_call_is_not_wrapped_in_a_swallowing_except(db):
    """Structural: the inner try/except is gone, and must not come back as one
    that forgets to re-raise."""
    tree = ast.parse(WORKER_SOURCE.read_text())

    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_batch"
    )

    for handler in ast.walk(function):
        if not isinstance(handler, ast.ExceptHandler):
            continue

        reraises = any(
            isinstance(node, ast.Raise) for node in ast.walk(handler)
        )

        # Naming the bookkeeping call rather than accepting "any assignment".
        # The failure branches used to record the outcome by assigning to the
        # ORM object; they now hand it to _record_failure_out_of_band, which
        # rolls back first and commits on a clean transaction. An except that
        # does neither is one that swallows the failure.
        records = any(
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "_record_failure_out_of_band"
            for node in ast.walk(handler)
        )

        assert reraises or records, (
            f"except at line {handler.lineno} neither re-raises nor records "
            "the failure durably"
        )


# ---------------------------------------------------------------------------
# Source guards: no prints anywhere on this path
# ---------------------------------------------------------------------------


def _print_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())

    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]


@pytest.mark.parametrize(
    "path", [WORKER_SOURCE, POSTGRES_SOURCE, MAIN_SOURCE],
    ids=["outbox_worker", "postgres", "main"],
)
def test_no_print_remains(path):
    """Parsed, not grepped: these modules discuss the removed prints in comments
    and docstrings on purpose."""
    assert _print_lines(path) == [], f"print() in {path.name}"


def test_the_worker_never_logs_a_whole_payload():
    """`event.payload` may be read for its keys, never passed as a value.

    The distinction is the point of the change, so it is asserted on the code as
    well as on the output: sorted(event.payload) yields keys, event.payload
    yields the body.
    """
    tree = ast.parse(WORKER_SOURCE.read_text())

    offenders = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue

        if getattr(node.func.value, "id", None) != "logger":
            continue

        for keyword in node.keywords:
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue

            for key, value in zip(keyword.value.keys, keyword.value.values):
                name = getattr(key, "value", None)

                if name == "payload_keys":
                    continue

                # Both spellings the body reaches a log by: the attribute on the
                # row, and the local unpacked from it at the top of the function.
                body = (
                    isinstance(value, ast.Attribute) and value.attr == "payload"
                ) or (
                    isinstance(value, ast.Name) and value.id == "payload"
                )

                if body:
                    offenders.append((node.lineno, name))

    assert not offenders, (
        f"logger calls passing the payload body: {offenders}"
    )


# ---------------------------------------------------------------------------
# Alembic no longer silences the application's loggers
# ---------------------------------------------------------------------------


def test_alembic_env_disables_no_existing_loggers():
    """AST, so a comment mentioning the flag cannot satisfy it."""
    tree = ast.parse(ALEMBIC_ENV.read_text())

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fileConfig"
    ]

    assert calls, "alembic/env.py no longer configures logging at all"

    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}

        assert "disable_existing_loggers" in keywords, (
            "fileConfig defaults to disabling every existing logger"
        )

        value = keywords["disable_existing_loggers"]

        assert isinstance(value, ast.Constant) and value.value is False


def test_application_loggers_survive_the_migration():
    """The behavioural half, and the one that actually failed before.

    conftest runs `alembic upgrade head` once per session, AFTER importing the
    application. Every logger below existed at that point, so with the old
    default each one had disabled = True for the rest of the run and every
    logger.info() in the codebase returned silently.
    """
    for name in (
        "app.services.outbox_service",
        "app.workers.outbox_worker",
        "app.services.event_handlers.notification_whatsapp_handler",
        "app.services.appointment_service",
        "app.task.appointment_reminders",
    ):
        assert logging.getLogger(name).disabled is False, (
            f"{name} was disabled by the migration's logging config"
        )


# ---------------------------------------------------------------------------
# Startup: the database is identified without a print and without a secret
# ---------------------------------------------------------------------------


def test_importing_the_database_module_prints_nothing(capsys):
    """The old print ran at import time, so that is where this looks."""
    import importlib

    capsys.readouterr()

    importlib.reload(postgres_module)

    captured = capsys.readouterr()

    assert captured.out == ""
    assert "APP CONNECTING TO DB" not in captured.out


def test_the_database_module_reads_no_credential_for_display():
    """It still builds the engine from database_url — that is its job. What it
    must not do is hand any of it to an output function."""
    tree = ast.parse(POSTGRES_SOURCE.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"print", "input"}


def test_the_startup_record_identifies_the_database_without_a_secret():
    """The structured replacement, asserted on the code because it lives in the
    lifespan and the lifespan skips its startup block under TESTING=1."""
    from app.config import get_settings

    tree = ast.parse(MAIN_SOURCE.read_text())

    target = None

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue

        if node.func.attr != "info" or getattr(node.func.value, "id", None) != "logger":
            continue

        if node.args and isinstance(node.args[0], ast.Constant) and (
            node.args[0].value == "database_connection_configured"
        ):
            target = node

    assert target is not None, "the startup record is gone"

    extra = next(kw.value for kw in target.keywords if kw.arg == "extra")

    keys = {
        key.value for key in extra.keys if isinstance(key, ast.Constant)
    }

    assert keys == {"db_host", "db_port", "db_name"}

    dumped = ast.dump(extra)

    for forbidden in ("POSTGRES_PASSWORD", "POSTGRES_USER", "database_url"):
        assert forbidden not in dumped

    # And the value that must never appear, checked against the real setting.
    settings = get_settings()

    assert settings.POSTGRES_PASSWORD not in MAIN_SOURCE.read_text()
