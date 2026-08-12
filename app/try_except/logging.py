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

#: Attributes logging itself puts on every LogRecord. They are not structured
#: extras and are not subject to the allowlist below: this formatter has always
#: excluded them from its output and continues to.
#:
#: `message` and `asctime` are here because a Formatter can set them on the
#: record, and `taskName` because Python 3.12 adds it to every record — without
#: it, an asyncio field would be indistinguishable from a developer's extra.
_STANDARD_LOGRECORD_ATTRS = frozenset({
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
    "taskName",
    "message",
    "asctime",
})


#: Attributes third-party libraries attach to records we do not control.
#: Neither emitted nor reported as dropped: reporting them would put
#: `dropped_extra_fields: ["color_message"]` on every uvicorn startup line,
#: which is noise a developer learns to ignore — and a dropped-field report
#: that is usually noise is a report nobody reads when it matters.
#:
#: uvicorn passes `color_message`, an ANSI-coloured duplicate of the message
#: it has already logged (uvicorn/server.py). Nothing is lost by omitting it.
_IGNORED_LIBRARY_ATTRS = frozenset({
    "color_message",
})


#: THE SECURITY BOUNDARY: an extra field is emitted only if it is named here.
#:
#: This is an allowlist and not a denylist on purpose. A denylist of `phone`,
#: `access_token`, `password` stops exactly those three spellings, and the next
#: leak arrives as `patient_phone`, `token_value`, `recipient` or
#: `prescription_text` — names nobody thought to forbid, in a log line written
#: months later by someone who never read the denylist. The failure mode of an
#: allowlist is a missing field in a log, which a developer notices and fixes.
#: The failure mode of a denylist is a patient's phone number in production
#: logs, which nobody notices at all.
#:
#: Every name below was taken from a real `extra={...}` in this repository and
#: reviewed against the value actually passed to it, not against how the name
#: reads. Names that survived that review are grouped by what they are for.
#: Names that did not are listed in REVIEWED_AND_EXCLUDED with the reason.
#:
#: Adding a name here is a security decision. The question to answer is not
#: "is this useful?" but "what is the worst value that could ever reach this
#: key?" — a key like `details` or `payload` fails that question whatever it
#: happens to hold today.
ALLOWED_EXTRA_FIELDS = frozenset({
    # -- identity and correlation ------------------------------------------
    # Database ids and opaque trace ids. Pseudonymous: they identify a row to
    # someone who already has database access, and carry no content.
    "request_id",
    "correlation_id",
    "user_id",
    "clinic_id",
    "event_id",
    "event_type",
    "family_id",
    "actor_id",
    "actor_user_id",
    "actor_role",
    "changed_by",
    "patient_id",
    "doctor_id",
    "appointment_id",
    "payment_id",
    "prescription_id",
    "recipient_id",
    "transaction_id",
    "gateway_payment_id",
    "resource",
    "resource_id",
    "resource_type",
    "lock_id",
    "media_id",
    # Celery puts these on a task's records (celery/app/log.py): an opaque
    # uuid and a dotted task path. Useful, and neither can carry content.
    "task_id",
    "task_name",

    # -- what happened -----------------------------------------------------
    "action",
    "op",
    "method",
    "path",
    "status",
    "status_code",
    "payment_status",
    "transaction_status",
    "gateway",
    "current",
    "target",
    "from_status",
    "to_status",

    # -- failure diagnostics -----------------------------------------------
    # `error` is `str(exc)` at most call sites. It is allowed because an error
    # log without the error is not worth writing; see the residual-risk note
    # in the module docstring of the formatter's tests.
    "error",
    "error_type",
    "reason",
    "detail",
    "sqlstate",
    "constraint",
    # The WhatsApp error fingerprint (`_error_fingerprint`) builds these at
    # runtime instead of logging Meta's response body.
    "error_code",
    "error_subcode",
    "error_fbtrace_id",
    "error_body",

    # -- retries and timing ------------------------------------------------
    "attempt",
    "attempts",
    "max_attempts",
    "retry_count",
    "next_retry_at",
    "cutoff",
    "duration_ms",
    "wait_time",
    "minutes_until_appointment",
    "retention_days",

    # -- counts and sizes --------------------------------------------------
    # Aggregates. A count cannot identify anyone.
    "count",
    "deleted",
    "processed",
    "remaining",
    "recorded",
    "returned",
    "size",
    "limit",
    "max_batches",
    "subscribers",
    "sessions_revoked",
    "appointments_marked",
    "due_appointments",
    "total_connections",

    # -- shapes, not contents ----------------------------------------------
    # `payload_keys` is the deliberate safe counterpart to logging a payload:
    # the key names, never the values.
    "payload_keys",
    "allowed",
    "user_field",
    "template_name",
    "setting",
    "channel",
    "key",
    "purpose",

    # -- money -------------------------------------------------------------
    # Reviewed and allowed: reconciliation mismatches are undiagnosable
    # without the two figures that disagree, and an amount is not an
    # identifier. They appear alongside payment_id, so treat these lines as
    # financial data under the same access controls as the database.
    "amount",
    "expected",
    "received",
    "expected_amount",
    "paid_amount",
    "received_amount",

    # -- deployment context ------------------------------------------------
    # Which database and mail host a process attached to. No credentials:
    # `password_length` is a length, which answers "is one configured?"
    # without being one.
    "environment",
    "host",
    "port",
    "db_host",
    "db_port",
    "db_name",
    "password_length",
    "logo_path",
})


#: Field names found in this repository's `extra={...}` calls and deliberately
#: NOT allowed. Documentation, not the mechanism — the mechanism is that
#: ALLOWED_EXTRA_FIELDS does not contain them, which is equally true of every
#: name nobody has thought of yet. Kept so the decision is reviewable, and
#: asserted by the formatter's tests so it cannot be quietly reversed.
REVIEWED_AND_EXCLUDED = {
    # The whole bKash response dict, including the payer's customerMsisdn —
    # a patient phone number, at INFO, on every payment execution.
    "result": "raw payment gateway response body",
    # The push notification body: title and message text written for a patient.
    "payload": "notification body / event payload",
    # An arbitrary caller-supplied dict on every audit event.
    "details": "unbounded caller-supplied dict",
    # The recipient's email address, and the subject line written about them.
    "to": "email recipient address",
    "subject": "message subject line",
    # `from`/`to` also spell an appointment status transition. Those two call
    # sites use from_status/to_status now, so the pair could be excluded here
    # without losing the transition log.
    "from": "ambiguous: email sender / status transition",
    # SMTP account and sender address. `_startup_context` already established
    # that a username is left out of a log even when the password is.
    "username": "smtp account identifier",
    "from_email": "sender email address",
    # A storage object key. Its diagnostic value is covered by
    # prescription_id, and a key named *_key does not belong in an allowlist.
    "signature_key": "storage object key; reads as a credential",
}


#: Names of dropped fields are reported under this key so a developer can see
#: that something was withheld. Never the values.
DROPPED_FIELDS_KEY = "dropped_extra_fields"


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

        # Partition the record's own attributes into approved extras and
        # everything else. Anything not named in the allowlist — a sensitive
        # field, a typo, or a field invented after this line was written — is
        # not emitted.
        extras = {}
        dropped = []

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS or key in _IGNORED_LIBRARY_ATTRS:
                continue

            if key in ALLOWED_EXTRA_FIELDS:
                extras[key] = value
            else:
                dropped.append(key)

        log_record.update(extras)

        if dropped:
            # Names only. Sorted so the field is stable to assert on and to
            # diff between log lines.
            #
            # Set after the update above, so an extra literally named
            # dropped_extra_fields cannot forge it: that name is not in the
            # allowlist either, so it lands in this list instead.
            log_record[DROPPED_FIELDS_KEY] = sorted(dropped)

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
