"""What the booking idempotency key is a key TO.

An Idempotency-Key promises that repeating a request repeats its effect rather
than duplicating it. That promise only holds if "the same request" is decided
by everything the request does. The hash is built from the request body:

    request_body = {"doctor_id": ..., "scheduled_at": ...}

and patient_id is absent from it, even though the route accepts patient_id and
books for that person. So two bookings that differ ONLY in who they are for
hash identically. The second is answered from the first one's stored response:
no appointment is created, and the caller is told one was — with the first
patient's appointment id.

The guard that exists for this is `record.request_hash != request_hash`, which
raises "Idempotency key reused with different request". Leaving patient_id out
of the hash is what stops that guard from firing on a genuinely different
request.

This is a correctness bug rather than a tenant one — reception reusing a key
across two patients at the desk is the realistic path, not an attack — but the
symptom is a patient who was never booked and a front desk that believes they
were.
"""

import pytest

from app.services.idempotency_service import create_request_hash


def test_the_hash_distinguishes_two_patients():
    """The unit the route's mismatch guard depends on."""

    first = create_request_hash(
        {"doctor_id": 7, "scheduled_at": "2026-09-01T10:00:00+00:00", "patient_id": 11}
    )
    second = create_request_hash(
        {"doctor_id": 7, "scheduled_at": "2026-09-01T10:00:00+00:00", "patient_id": 12}
    )

    assert first != second


def test_the_route_puts_the_patient_in_the_hash():
    """Asserted against the route's own construction rather than a copy of it.

    A unit test of create_request_hash alone would keep passing while the route
    goes on hashing two of the three fields it acts on, which is exactly the
    defect.
    """

    import ast
    import pathlib

    import app.api.routes.appointments as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text())

    hashed_keys = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        target = node.targets[0]

        if getattr(target, "id", None) != "request_body":
            continue

        if isinstance(node.value, ast.Dict):
            hashed_keys = {
                k.value for k in node.value.keys if isinstance(k, ast.Constant)
            }

    assert hashed_keys is not None, "request_body is no longer a literal dict"

    assert "patient_id" in hashed_keys, (
        "the booking idempotency hash omits patient_id, so two bookings that "
        f"differ only in who they are for collide; hashed: {sorted(hashed_keys)}"
    )

    # The other two are what make the key specific to a booking at all.
    assert {"doctor_id", "scheduled_at"} <= hashed_keys
