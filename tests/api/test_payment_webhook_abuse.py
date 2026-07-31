"""The bKash webhook is unauthenticated by necessity — bounding what that costs.

bKash returns the user's BROWSER to the callback URL, so there is no
server-to-server request to sign; a signature header is not available and
requiring one would break the integration outright.

Forgery is already prevented by design: nothing in the payload is trusted, and
the amount and status come from a server-to-server execute_payment() call
against bKash. What was NOT bounded was the work an anonymous POST could cause
before reaching that point — a database write and an outbound gateway call per
request, with any invented paymentID.
"""

import pytest
from sqlalchemy import func, select

from app.models.idempotency_key import IdempotencyKey


async def _idempotency_rows(db) -> int:
    return await db.scalar(select(func.count()).select_from(IdempotencyKey)) or 0


@pytest.mark.asyncio
async def test_unknown_payment_id_is_rejected(client):
    res = await client.post(
        "/payments/webhook/bkash",
        json={"paymentID": "TR0011-does-not-exist"},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_unknown_payment_id_writes_no_idempotency_row(client, db):
    """An anonymous POST must not be able to grow our tables."""
    before = await _idempotency_rows(db)

    for i in range(5):
        await client.post(
            "/payments/webhook/bkash",
            json={"paymentID": f"forged-{i}"},
        )

    assert await _idempotency_rows(db) == before, (
        "unauthenticated requests created idempotency rows — unbounded growth"
    )


@pytest.mark.asyncio
async def test_unknown_payment_id_never_calls_the_gateway(client, monkeypatch):
    """The expensive half: do not let strangers make us call bKash.

    Each outbound call uses our credentials. A flood of invented ids would get
    the account rate-limited or flagged, taking real payments down with it.
    """
    called = []

    import app.services.payment_webhook_service as svc

    def _explode(*args, **kwargs):
        called.append(1)
        raise AssertionError("gateway was called for an unknown payment id")

    monkeypatch.setattr(svc, "get_payment_gateway", _explode)

    res = await client.post(
        "/payments/webhook/bkash",
        json={"paymentID": "forged-no-gateway-call"},
    )

    assert res.status_code == 404
    assert not called, "outbound gateway call made for an unknown payment id"


@pytest.mark.asyncio
async def test_malformed_payload_is_refused_before_anything_else(client, db):
    before = await _idempotency_rows(db)

    res = await client.post("/payments/webhook/bkash", json={})

    assert res.status_code == 422
    assert await _idempotency_rows(db) == before
