"""The outbox worker must not put the database password in its logs.

It used to open with

    print("WORKER DB URL:", settings.database_url)

which wrote the whole connection string — password included — to stdout on every
worker start, and so into container logs and anything shipping them onward. A
password in a log is a password that has leaked, however private the log is
meant to be.

The operational question that print was answering is a fair one: a worker
attached to the wrong database is a real incident and hard to notice. So the
answer survives as host, port and database name, and the secret does not.

These tests assert the property — the password does not appear in what the
worker emits — rather than the absence of one particular line, because the next
version of this mistake will not be spelled the same way.
"""

import ast
import json
import logging
from pathlib import Path

import pytest

from app.config import get_settings
from app.try_except.logging import JsonFormatter
from app.workers.run_outbox_worker import _startup_context

WORKER_SOURCE = (
    Path(__file__).parent.parent.parent / "app" / "workers" / "run_outbox_worker.py"
)


# ---------------------------------------------------------------------------
# The diagnostic carries no credentials
# ---------------------------------------------------------------------------


def test_the_startup_context_contains_no_password():
    settings = get_settings()

    values = {str(v) for v in _startup_context().values()}

    assert settings.POSTGRES_PASSWORD not in values
    assert not any(settings.POSTGRES_PASSWORD in v for v in values), (
        "the database password appears in the worker's startup diagnostic"
    )


def test_the_startup_context_contains_no_username():
    """Half a credential is still a credential, and it identifies nothing that
    host, port and database name do not."""
    settings = get_settings()

    values = {str(v) for v in _startup_context().values()}

    assert not any(settings.POSTGRES_USER in v for v in values)


def test_the_startup_context_still_answers_which_database():
    """The diagnostic was removed for its secret, not its usefulness. A worker
    pointed at the wrong database has to remain diagnosable."""
    settings = get_settings()

    context = _startup_context()

    assert context["db_host"] == settings.POSTGRES_HOST
    assert context["db_port"] == settings.POSTGRES_PORT
    assert context["db_name"] == settings.POSTGRES_DB


def test_the_startup_context_holds_nothing_else():
    """Pinned so a later addition cannot quietly reintroduce a secret through
    this dictionary."""
    assert set(_startup_context()) == {"db_host", "db_port", "db_name"}


# ---------------------------------------------------------------------------
# Nothing the worker emits contains the password
# ---------------------------------------------------------------------------


def test_the_emitted_startup_log_line_contains_no_password():
    """Through the real formatter, because the leak was in what was WRITTEN.

    A dictionary that looks clean is not enough: the assertion has to be on the
    bytes the process emits.

    Formatted into an in-memory stream rather than captured from stderr. The
    root logger is global state that other tests in this suite reconfigure —
    setup_logging assigns root.handlers, and the app factory calls it — so a
    capsys-based version of this passed alone and captured nothing in the full
    run. What matters is what JsonFormatter produces for this record, and that
    can be asserted without touching global state at all.
    """
    import io

    settings = get_settings()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("app.workers.test_startup")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info("outbox_worker_started", extra=_startup_context())
    finally:
        logger.removeHandler(handler)

    emitted = stream.getvalue()

    assert emitted.strip(), "nothing was emitted"

    assert settings.POSTGRES_PASSWORD not in emitted, (
        "the worker's startup line still carries the database password"
    )
    assert settings.POSTGRES_USER not in emitted

    record = json.loads(emitted.strip().splitlines()[-1])

    assert record["message"] == "outbox_worker_started"
    assert record["db_name"] == settings.POSTGRES_DB


def test_importing_the_worker_prints_nothing(capsys):
    """The leak happened at IMPORT time, before any logging was configured, so
    it bypassed every handler and formatter."""
    import importlib

    import app.workers.run_outbox_worker as worker

    capsys.readouterr()

    importlib.reload(worker)

    captured = capsys.readouterr()
    emitted = (captured.out or "") + (captured.err or "")

    assert get_settings().POSTGRES_PASSWORD not in emitted
    assert "WORKER DB URL" not in emitted


# ---------------------------------------------------------------------------
# The shape that caused it cannot come back
# ---------------------------------------------------------------------------


def test_the_worker_module_never_reads_the_connection_url():
    """Parsed, not grepped.

    The docstring of _startup_context quotes the offending line on purpose, so a
    text search finds it and a source-level guard written that way would fail on
    its own explanation. This looks at code.
    """
    tree = ast.parse(WORKER_SOURCE.read_text())

    offenders = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr
        in {"database_url", "DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_USER"}
    ]

    assert not offenders, (
        f"the worker reads credential-bearing settings: {offenders}"
    )


def test_the_worker_prints_nothing_derived_from_settings():
    """print() bypasses logging entirely — no formatter, no redaction, no level.

    One credential-free print survives in the __main__ guard
    ("Worker stopped manually"); what must not return is a print of anything
    that came from settings.
    """
    tree = ast.parse(WORKER_SOURCE.read_text())

    offenders = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            continue

        for argument in node.args:
            for inner in ast.walk(argument):
                if isinstance(inner, ast.Name) and inner.id == "settings":
                    offenders.append(node.lineno)

    assert not offenders, (
        f"print() of settings-derived data at line(s) {offenders}"
    )


@pytest.mark.parametrize(
    "secret_attr", ["POSTGRES_PASSWORD", "POSTGRES_USER"]
)
def test_no_worker_entrypoint_logs_a_credential(secret_attr):
    """Extended to the Celery entrypoints too, since they now share the same
    structured logging and are the other place a startup diagnostic would go."""
    for module in (
        WORKER_SOURCE,
        WORKER_SOURCE.parent.parent / "core" / "celery.py",
        WORKER_SOURCE.parent.parent / "core" / "celery_logging.py",
    ):
        tree = ast.parse(module.read_text())

        found = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == secret_attr
        ]

        assert not found, f"{module.name} reads {secret_attr}"
