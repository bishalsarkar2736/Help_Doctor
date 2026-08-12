"""WhatsApp operational logs carry no patient data.

WHAT WAS LEAKING
Four statements in app/services/whatsapp_service.py:

    :86   error  whatsapp_send_document_failed  -> phone, response.text
    :99   info   whatsapp_document_sent         -> phone
    :159  error  whatsapp_media_upload_failed   -> response.text
    :241  error  whatsapp_send_template_failed  -> response.text

A phone number tied to a prescription delivery is identifiable health
information: it says this person is a patient of this clinic and was sent a
prescription. The `info` one fired on EVERY successful send, so it was routine
volume rather than an error-path edge case.

WHY THERE WAS NO SAFETY NET
JsonFormatter copies every non-standard LogRecord attribute straight into the
output:

    extras = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
    log_record.update(extras)

There is no redaction, no filter, and a repository-wide search for
redact/sanitize/filter found none anywhere. Whatever a call site puts in `extra`
is what ships to stdout, to the local driver's rotated files, and onward.

THE SUBTLE ONE
`whatsapp_send_template_failed` chose its own fields carefully -- template_name
only, no phone. It leaked anyway, because the request body twelve lines above is
`{"to": phone, ...}` and Meta echoes request context in 4xx bodies. The leak
arrived through a field name nobody would audit. That is why these tests assert
on the RENDERED OUTPUT rather than on the field names.

WHAT IS TESTED HERE
The real code path, with httpx mocked and TESTING disabled, formatted through
the production JsonFormatter, asserting the phone number does not appear in the
bytes that would be written.
"""

import json
import logging
import os

import httpx
import pytest

from app.services.whatsapp_service import WhatsAppService, _error_fingerprint
from app.try_except.logging import JsonFormatter

# Obvious fakes. The point is that these strings must not survive into a log
# line, so they are chosen to be unmistakable if they do.
PHONE = "+8801711999888"
TOKEN = "test-access-token-must-never-be-logged"

# A Meta-shaped error body that echoes the recipient, which is exactly what
# makes response.text unsafe.
META_ERROR_BODY = {
    "error": {
        "message": f"(#131030) Recipient phone number not in allowed list: {PHONE}",
        "type": "OAuthException",
        "code": 131030,
        "error_subcode": 2655007,
        "error_data": {"details": f"the number {PHONE} is not registered"},
        "fbtrace_id": "AbCdEfGhIjK",
    }
}


@pytest.fixture
def live_client(monkeypatch):
    """Turn off the TESTING short-circuit so the real path runs.

    whatsapp_service returns early when TESTING=1 -- a deliberate guard against
    calling Meta from the suite. These tests need the code AFTER that guard, so
    the guard is lifted and httpx is mocked instead: no network is possible.
    """
    monkeypatch.setenv("TESTING", "0")


def _post_returning(response: httpx.Response):
    """Replace httpx.AsyncClient.post with one that returns `response`."""

    async def fake_post(self, *args, **kwargs):
        return response

    return fake_post


def _response(status: int, body) -> httpx.Response:
    if isinstance(body, (dict, list)):
        return httpx.Response(status, json=body, request=httpx.Request("POST", "https://x"))

    return httpx.Response(status, text=body, request=httpx.Request("POST", "https://x"))


def _rendered(records: list[logging.LogRecord]) -> str:
    """Exactly what would be written, via the production formatter.

    Asserting on record.__dict__ would miss the question that matters; this
    renders the same JSON the container emits.
    """
    formatter = JsonFormatter()

    return "\n".join(formatter.format(record) for record in records)


# ---------------------------------------------------------------------------
# The failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_document_send_logs_no_phone_and_no_body(
    live_client, monkeypatch, caplog
):
    """THE REGRESSION. Both the argument and the echoed body are excluded."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post", _post_returning(_response(400, META_ERROR_BODY))
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            await WhatsAppService.send_document(
                phone=PHONE, media_id="m-1", filename="prescription_1.pdf"
            )

    output = _rendered(caplog.records)

    assert "whatsapp_send_document_failed" in output
    assert PHONE not in output, "the patient's phone number reached the log"
    assert "not in allowed list" not in output, "Meta's free text reached the log"
    assert "error_data" not in output


@pytest.mark.asyncio
async def test_a_failed_media_upload_logs_no_body(live_client, monkeypatch, caplog):
    monkeypatch.setattr(
        httpx.AsyncClient, "post", _post_returning(_response(400, META_ERROR_BODY))
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            await WhatsAppService.upload_media(pdf_bytes=b"%PDF-", filename="x.pdf")

    output = _rendered(caplog.records)

    assert "whatsapp_media_upload_failed" in output
    assert PHONE not in output
    assert "not in allowed list" not in output


@pytest.mark.asyncio
async def test_a_failed_template_send_logs_no_body(live_client, monkeypatch, caplog):
    """The statement whose own fields were already safe. It leaked through
    response.text echoing the recipient, so the assertion is on the output."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post", _post_returning(_response(400, META_ERROR_BODY))
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            await WhatsAppService.send_template(
                phone=PHONE, template_name="appointment_reminder"
            )

    output = _rendered(caplog.records)

    assert "whatsapp_send_template_failed" in output
    assert PHONE not in output
    assert "not in allowed list" not in output

    # The useful part is kept: which template Meta rejected.
    assert "appointment_reminder" in output


# ---------------------------------------------------------------------------
# The success path -- the highest-volume leak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_document_send_logs_no_phone(
    live_client, monkeypatch, caplog
):
    """This fired once per prescription delivered, on the happy path."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post", _post_returning(_response(200, {"messages": [{"id": "1"}]}))
    )

    with caplog.at_level(logging.INFO):
        await WhatsAppService.send_document(
            phone=PHONE, media_id="m-1", filename="prescription_1.pdf"
        )

    output = _rendered(caplog.records)

    assert "whatsapp_document_sent" in output
    assert PHONE not in output


@pytest.mark.asyncio
async def test_the_access_token_is_never_logged(live_client, monkeypatch, caplog):
    """It only ever reaches `headers`, which is never passed to a logger. Pinned
    because a future 'log the request for debugging' would break it."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "WHATSAPP_ACCESS_TOKEN", TOKEN)
    monkeypatch.setattr(
        httpx.AsyncClient, "post", _post_returning(_response(400, META_ERROR_BODY))
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            await WhatsAppService.send_template(phone=PHONE, template_name="t")

    assert TOKEN not in _rendered(caplog.records)


# ---------------------------------------------------------------------------
# The fingerprint keeps what is useful
# ---------------------------------------------------------------------------


def test_the_fingerprint_keeps_the_identifiers_support_asks_for():
    """Removing the body must not leave an operator with nothing. code, type and
    fbtrace_id are what a Meta support ticket needs."""
    fingerprint = _error_fingerprint(_response(400, META_ERROR_BODY))

    assert fingerprint["status"] == 400
    assert fingerprint["error_code"] == 131030
    # Meta names this one `error_subcode` already, so it is not re-prefixed.
    assert fingerprint["error_subcode"] == 2655007
    assert fingerprint["error_type"] == "OAuthException"
    assert fingerprint["error_fbtrace_id"] == "AbCdEfGhIjK"


def test_the_fingerprint_drops_every_free_text_field():
    """message, error_user_msg and error_data are where an echoed number or a
    message body would be."""
    fingerprint = _error_fingerprint(_response(400, META_ERROR_BODY))

    rendered = json.dumps(fingerprint)

    assert PHONE not in rendered
    assert "message" not in fingerprint
    assert "error_data" not in fingerprint
    assert "not in allowed list" not in rendered


def test_the_fingerprint_survives_a_non_json_body():
    """A gateway returning an HTML error page must not crash the send path, and
    must not have its body logged either."""
    fingerprint = _error_fingerprint(
        _response(502, f"<html>Bad gateway for {PHONE}</html>")
    )

    assert fingerprint["status"] == 502
    assert fingerprint["error_body"] == "unparseable"
    assert PHONE not in json.dumps(fingerprint)


@pytest.mark.parametrize("body", [{"error": "a string, not an object"}, {}, [1, 2], "plain"])
def test_the_fingerprint_never_raises(body):
    """A diagnostic must not be able to fail the operation it is diagnosing."""
    assert _error_fingerprint(_response(400, body))["status"] == 400


# ---------------------------------------------------------------------------
# Structural guard against the next one
# ---------------------------------------------------------------------------


def test_no_log_statement_in_the_service_names_a_sensitive_field():
    """The behavioural tests above cover the four known statements. This catches
    a fifth being added, which the rendered-output tests would not see."""
    import ast
    import pathlib

    import app.services.whatsapp_service as module

    sensitive = {
        "phone", "phone_number", "recipient", "to", "body", "text", "message",
        "content", "response", "parameters", "body_parameters", "token",
        "access_token", "authorization", "email", "name",
    }

    tree = ast.parse(pathlib.Path(module.__file__).read_text())

    offenders = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue

        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue

        for keyword in node.keywords:
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue

            keys = {k.value for k in keyword.value.keys if isinstance(k, ast.Constant)}

            for field in sorted(keys & sensitive):
                offenders.append(f"line {node.lineno}: extra={{'{field}': ...}}")

    assert not offenders, "sensitive fields in log extras:\n  " + "\n  ".join(offenders)


def test_response_text_is_never_read_in_this_module():
    """The specific shape that leaked: `"response": response.text`.

    Checked with the AST rather than by matching text: the module docstring and
    a comment both name `response.text` deliberately, to record what the bug
    was. A string search cannot tell an explanation from an access, and
    forbidding the explanation would be the wrong thing to enforce -- the same
    lesson the monitoring guards learned.
    """
    import ast
    import pathlib

    import app.services.whatsapp_service as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text())

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "text"
        and isinstance(node.value, ast.Name)
        and node.value.id == "response"
    ]

    assert not offenders, (
        f"response.text is read at line(s) {offenders}; Meta echoes the "
        "recipient's number in error bodies"
    )
