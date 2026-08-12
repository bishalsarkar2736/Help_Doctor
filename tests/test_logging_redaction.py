"""The logging allowlist: what JsonFormatter is permitted to emit.

WHAT WAS WRONG
JsonFormatter copied every non-standard LogRecord attribute into its JSON output:

    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key not in standard_attrs
    }

So `logger.info("x", extra={"phone": phone, "access_token": token})` wrote both
values to stdout, into container logs, and into anything collecting them. The
repository-wide audit behind this change found five call sites already doing a
version of that, the worst being the whole bKash response dict — which contains
the payer's customerMsisdn — at INFO on every payment execution.

WHY AN ALLOWLIST
A denylist of `phone`, `access_token`, `password` stops those three spellings.
The next leak arrives as `patient_phone`, `recipient`, `token_value` or
`prescription_text`, and a denylist cannot forbid a name nobody has thought of.
The tests below therefore assert the boundary in the only direction that matters
for security: an UNKNOWN field is dropped, which is a statement about every
field name that does not exist yet.

These tests format records through the real production JsonFormatter and read
the rendered JSON. None of them inspects the formatter's source, because source
that looks correct and output that is correct are different claims.

RESIDUAL RISK, RECORDED DELIBERATELY
The allowlist stops unknown keys. It cannot stop an approved key being misused:
`error` holds `str(exc)` at fifteen call sites, and an exception string can in
principle quote a value that was passed to it. `error` is allowed anyway, since
an error log without the error is not worth writing. The mitigation is review of
what goes into `error`, not the allowlist — and the allowlist is what stops the
new field a developer adds next to it.
"""

import json
import logging

import pytest

from app.try_except.logging import (
    ALLOWED_EXTRA_FIELDS,
    DROPPED_FIELDS_KEY,
    REVIEWED_AND_EXCLUDED,
    JsonFormatter,
)

PHONE = "+8801711999888"
TOKEN = "EAAGm0PX4ZoPQBO7super-secret-token"


def render(message: str = "event", *, level: int = logging.INFO, exc_info=None,
           **extra) -> str:
    """One log line, exactly as the production formatter would write it."""
    record = logging.LogRecord(
        "app.test", level, "f.py", 1, message, None, exc_info
    )

    # logging.Logger.makeRecord copies `extra` onto the record verbatim; doing
    # the same here keeps the test faithful to how extras actually arrive.
    for key, value in extra.items():
        setattr(record, key, value)

    return JsonFormatter().format(record)


def emitted(message: str = "event", **extra) -> dict:
    return json.loads(render(message, **extra))


# ---------------------------------------------------------------------------
# 1, 2. The boundary
# ---------------------------------------------------------------------------


def test_an_approved_field_is_emitted():
    out = emitted(event_id="evt-123")

    assert out["event_id"] == "evt-123"


def test_an_unknown_field_is_dropped():
    """THE SECURITY PROPERTY. Not "these names are dropped" but "a name the
    allowlist does not know is dropped" — which covers every field that does
    not exist yet."""
    out = emitted(some_field_invented_later="value")

    assert "some_field_invented_later" not in out


def test_an_unknown_fields_value_appears_nowhere_in_the_line():
    """Dropped means absent from the rendered bytes, not merely absent from a
    parsed key — a value copied into the message or an exception would still
    have leaked."""
    line = render(unheard_of_field="the-sensitive-value")

    assert "the-sensitive-value" not in line


# ---------------------------------------------------------------------------
# 3-11. The names that motivated the change, and the ones that did not exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("phone", PHONE),
        ("patient_phone", PHONE),
        ("phone_number", PHONE),
        ("recipient", PHONE),
        ("access_token", TOKEN),
        ("token", TOKEN),
        ("token_value", TOKEN),
        ("password", "hunter2"),
        ("authorization", "Bearer " + TOKEN),
        ("secret", "shhh"),
        ("api_key", "ak_live_12345"),
        ("prescription_content", "amoxicillin 500mg tds"),
        ("prescription_text", "amoxicillin 500mg tds"),
        ("diagnosis", "type 2 diabetes"),
        ("medical_data", "hba1c 8.2"),
        ("request_body", '{"card": "4242424242424242"}'),
        ("response_body", '{"customerMsisdn": "' + PHONE + '"}'),
        ("email", "patient@example.com"),
        ("address", "12 Road 3, Dhaka"),
        ("card_number", "4242424242424242"),
        # Not sensitive-sounding at all. Still dropped, because unknown.
        ("future_field", "anything"),
    ],
)
def test_sensitive_or_unknown_field_is_dropped(field, value):
    line = render(**{field: value})
    out = json.loads(line)

    assert field not in out, f"{field} was emitted"
    assert value not in line, f"the value of {field} reached the log line"


def test_none_of_the_sensitive_names_are_on_the_allowlist():
    """The parametrised cases above prove the behaviour; this pins the intent,
    so a future edit to the allowlist has to break a named assertion rather
    than quietly widening the boundary."""
    forbidden = {
        "phone", "patient_phone", "phone_number", "recipient", "recipient_phone",
        "access_token", "token", "token_value", "refresh_token",
        "password", "passwd", "authorization", "auth", "secret", "api_key",
        "prescription_content", "prescription_text", "diagnosis", "medical_data",
        "request_body", "response_body", "body", "content", "text",
        "email", "address", "card_number", "otp", "mfa_secret",
    }

    assert not (forbidden & ALLOWED_EXTRA_FIELDS)


# ---------------------------------------------------------------------------
# 12. Mixed safe and unsafe, which is how a real leak looks
# ---------------------------------------------------------------------------


def test_the_required_regression_case():
    """The exact case from the security review that prompted this milestone."""
    line = render(
        "privacy_test",
        event_id="evt-123",
        phone=PHONE,
        access_token="super-secret",
        future_secret="do-not-log",
    )
    out = json.loads(line)

    assert out["event_id"] == "evt-123"

    assert "phone" not in out
    assert "access_token" not in out
    assert "future_secret" not in out

    # And the values themselves, anywhere in the rendered JSON.
    assert PHONE not in line
    assert "super-secret" not in line
    assert "do-not-log" not in line


def test_a_safe_field_survives_alongside_unsafe_ones():
    out = emitted(
        appointment_id=7,
        patient_id=42,
        phone=PHONE,
        prescription_content="amoxicillin",
    )

    assert out["appointment_id"] == 7
    assert out["patient_id"] == 42
    assert "phone" not in out
    assert "prescription_content" not in out


def test_dropping_one_field_does_not_drop_the_others():
    """A single unknown field must not cost the whole extras dict — the failure
    mode that would push developers back to interpolating values into the
    message string."""
    out = emitted(event_id="evt-1", event_type="PAYMENT_FAILED",
                  user_id=5, mystery="x")

    assert out["event_id"] == "evt-1"
    assert out["event_type"] == "PAYMENT_FAILED"
    assert out["user_id"] == 5
    assert "mystery" not in out


# ---------------------------------------------------------------------------
# 7. Observability: names, never values
# ---------------------------------------------------------------------------


def test_dropped_field_names_are_reported():
    out = emitted(event_id="ok", phone=PHONE, future_secret="s")

    assert out[DROPPED_FIELDS_KEY] == ["future_secret", "phone"]


def test_the_report_never_contains_the_dropped_values():
    line = render(phone=PHONE, access_token=TOKEN)
    out = json.loads(line)

    assert out[DROPPED_FIELDS_KEY] == ["access_token", "phone"]
    assert PHONE not in line
    assert TOKEN not in line


def test_the_report_is_absent_when_nothing_was_dropped():
    """Otherwise every well-behaved log line carries an empty list forever."""
    out = emitted(event_id="evt-1")

    assert DROPPED_FIELDS_KEY not in out


def test_the_report_cannot_be_forged_by_an_extra_of_the_same_name():
    """A caller passing dropped_extra_fields must not be able to overwrite the
    formatter's own account of what it withheld."""
    out = emitted(**{DROPPED_FIELDS_KEY: ["nothing_was_dropped"], "phone": PHONE})

    assert out[DROPPED_FIELDS_KEY] == [DROPPED_FIELDS_KEY, "phone"]


# ---------------------------------------------------------------------------
# 2, 8, 9. Nothing that already worked stops working
# ---------------------------------------------------------------------------


def test_the_base_fields_are_unchanged():
    out = emitted("hello")

    assert out["message"] == "hello"
    assert out["level"] == "INFO"
    assert out["logger"] == "app.test"
    for key in ("timestamp", "request_id", "correlation_id", "user_id", "clinic_id"):
        assert key in out


def test_standard_logrecord_attributes_are_not_reported_as_dropped():
    """They were never emitted and are not extras. Reporting them would put
    `filename`, `lineno` and `thread` in dropped_extra_fields on every line."""
    out = emitted("hello")

    assert DROPPED_FIELDS_KEY not in out


def test_taskName_is_no_longer_emitted():
    """Python 3.12 adds taskName to every record. The old standard-attribute
    set predates it, so it was emitted as `"taskName": null` on every line;
    it is a logging field, not a developer's extra."""
    out = emitted("hello")

    assert "taskName" not in out


def test_a_third_party_record_attribute_is_dropped_without_being_reported():
    """uvicorn attaches color_message to its own startup lines. Reporting it
    would mark every one of them as having had a field withheld, which trains
    developers to ignore the field that exists to be noticed."""
    out = emitted("Started server process", color_message="\033[36mStarted\033[0m")

    assert "color_message" not in out
    assert DROPPED_FIELDS_KEY not in out


def test_a_third_party_attribute_does_not_hide_a_real_drop():
    out = emitted("x", color_message="c", phone=PHONE)

    assert out[DROPPED_FIELDS_KEY] == ["phone"]
    assert "color_message" not in out


def test_celery_task_identifiers_survive():
    out = emitted("task ran", task_id="8f2c-…", task_name="app.task.reminders")

    assert out["task_id"] == "8f2c-…"
    assert out["task_name"] == "app.task.reminders"


def test_exception_logging_still_carries_the_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        line = render("failed", level=logging.ERROR, exc_info=sys.exc_info())

    out = json.loads(line)

    assert "Traceback (most recent call last)" in out["exception"]
    assert "ValueError: boom" in out["exception"]
    assert "raise ValueError" in out["exception"]


def test_exception_logging_still_applies_the_allowlist():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        line = render("failed", level=logging.ERROR, exc_info=sys.exc_info(),
                      event_id="evt-9", phone=PHONE)

    out = json.loads(line)

    assert out["event_id"] == "evt-9"
    assert "exception" in out
    assert "phone" not in out
    assert PHONE not in line


def test_output_is_valid_json_in_every_shape():
    import sys

    lines = [render("plain")]
    lines.append(render("approved", event_id="e", user_id=1))
    lines.append(render("unknown", mystery="m"))
    lines.append(render("mixed", event_id="e", phone=PHONE))
    try:
        raise RuntimeError("x")
    except RuntimeError:
        lines.append(render("boom", level=logging.ERROR, exc_info=sys.exc_info()))

    for line in lines:
        parsed = json.loads(line)          # raises if not valid JSON
        assert isinstance(parsed, dict)


def test_an_allowed_field_may_hold_a_non_string_value():
    """Ints, floats, lists, dicts and None all survived the old formatter and
    still have to."""
    out = emitted(
        count=3,
        amount=500.5,
        payload_keys=["a", "b"],
        error_body="unparseable",
        next_retry_at=None,
    )

    assert out["count"] == 3
    assert out["amount"] == 500.5
    assert out["payload_keys"] == ["a", "b"]
    assert out["next_retry_at"] is None


def test_an_extra_still_overrides_the_context_user_id():
    """Longstanding behaviour: 26 call sites pass user_id explicitly, and it
    has always won over the contextvar."""
    from app.try_except.context import user_id_ctx

    user_id_ctx.set(1)
    try:
        out = emitted(user_id=999)
    finally:
        user_id_ctx.set(None)

    assert out["user_id"] == 999


# ---------------------------------------------------------------------------
# The reviewed exclusions, pinned
# ---------------------------------------------------------------------------


def test_the_reviewed_exclusions_are_really_excluded():
    """REVIEWED_AND_EXCLUDED is documentation; this makes it enforceable, so
    the reason recorded there cannot drift from the allowlist's contents."""
    overlap = set(REVIEWED_AND_EXCLUDED) & ALLOWED_EXTRA_FIELDS

    assert not overlap, f"excluded for a reason, yet allowed: {sorted(overlap)}"


@pytest.mark.parametrize("field", sorted(REVIEWED_AND_EXCLUDED))
def test_each_reviewed_exclusion_is_dropped_at_runtime(field):
    value = f"sensitive-{field}-value"
    line = render(**{field: value})

    assert field not in json.loads(line)
    assert value not in line


def test_the_known_gateway_response_leak_is_closed():
    """payment_webhook_service logs the bKash execute response as `result`. A
    real one carries the payer's phone in customerMsisdn."""
    bkash_response = {
        "transactionStatus": "Completed",
        "customerMsisdn": PHONE,
        "trxID": "8A2B3C4D",
        "amount": "500",
    }

    line = render("bkash_execute_response",
                  gateway_payment_id="TR0011abc", result=bkash_response)
    out = json.loads(line)

    assert out["gateway_payment_id"] == "TR0011abc"
    assert "result" not in out
    assert PHONE not in line
    assert "8A2B3C4D" not in line


def test_the_known_email_recipient_leak_is_closed():
    line = render("Failed to send email",
                  to="patient@example.com", subject="Your prescription is ready")
    out = json.loads(line)

    assert "to" not in out
    assert "subject" not in out
    assert "patient@example.com" not in line
    assert "prescription" not in line


def test_the_known_notification_payload_leak_is_closed():
    payload = {"title": "Payment failed",
               "body": f"Dear patient, your payment for {PHONE} failed"}

    line = render("push_notification_failed", user_id=4, payload=payload)
    out = json.loads(line)

    assert out["user_id"] == 4
    assert "payload" not in out
    assert PHONE not in line


def test_the_smtp_config_line_keeps_only_what_it_needs():
    """host/port/password_length answer "is SMTP configured and where" without
    the account name or the password itself."""
    out = emitted("smtp_config", host="smtp.example.com", port=587,
                  username="clinic@example.com", password_length=16,
                  from_email="noreply@example.com")

    assert out["host"] == "smtp.example.com"
    assert out["port"] == 587
    assert out["password_length"] == 16
    assert "username" not in out
    assert "from_email" not in out


# ---------------------------------------------------------------------------
# The allowlist itself stays reviewable
# ---------------------------------------------------------------------------


def test_the_allowlist_holds_no_obviously_sensitive_name():
    """A guard against the allowlist being widened carelessly later: no
    approved field may be named after a credential, a body or a phone."""
    substrings = (
        "phone", "msisdn", "passwd", "password_", "secret", "token",
        "authorization", "credential", "api_key", "apikey",
        "diagnos", "medic", "prescription_", "body", "content",
    )

    # Deliberate near-misses. Each is named for something sensitive and holds
    # something that is not, so each is recorded with the reason rather than
    # excused by weakening the needles above — a new offender still fails.
    near_misses = {
        "password_length": "a length; answers 'is one set?' without being one",
        "error_body": "only ever the constant 'unparseable'",
        "prescription_id": "a row id, not prescription contents",
    }

    offenders = sorted(
        field for field in ALLOWED_EXTRA_FIELDS
        for needle in substrings
        if needle in field.lower()
    )

    assert offenders == sorted(near_misses), offenders


def test_every_allowed_field_is_a_plain_identifier():
    """Keys are emitted into JSON verbatim; a stray space or quote would be a
    sign the allowlist had been edited from something other than real keys."""
    for field in ALLOWED_EXTRA_FIELDS:
        assert field.isidentifier() or field == "from_status", field
