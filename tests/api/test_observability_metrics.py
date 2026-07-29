import pytest

from app.core.metrics import login_attempts_total


@pytest.mark.asyncio
async def test_metrics_endpoint_lists_new_counters(client):
    res = await client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    # Unlabeled counters are exported at 0 as soon as they're registered.
    for name in (
        "payments_success_total",
        "payments_failed_total",
        "prescriptions_issued_total",
    ):
        assert name in body


@pytest.mark.asyncio
async def test_failed_login_increments_metric(client):
    child = login_attempts_total.labels(result="failure")
    before = child._value.get()

    res = await client.post(
        "/auth/login-json",
        json={"email": "does-not-exist@test.com", "password": "wrongpass1"},
    )
    assert res.status_code == 401

    assert child._value.get() == before + 1
