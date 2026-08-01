"""HTTP request metrics — counts, statuses, and the cardinality guard.

Without a status-labelled counter there is no error rate: the latency histogram
says how long requests took but not whether any of them failed, so a deploy
that 500s every write looks perfectly healthy on the dashboard.

The most important test here is the cardinality one. A `path` label carrying
the requested URL rather than the route template mints a new time series per
patient id and per scanner probe, and eventually takes Prometheus down with the
system it is meant to be watching.
"""

import pytest
from prometheus_client import generate_latest

from app.core.metrics import http_requests_total


def _samples():
    """Every http_requests_total sample as (labels, value)."""
    out = []
    for metric in http_requests_total.collect():
        for sample in metric.samples:
            if sample.name == "http_requests_total":
                out.append((sample.labels, sample.value))
    return out


def _value(method: str, path: str, status: str) -> float:
    for labels, value in _samples():
        if (
            labels.get("method") == method
            and labels.get("path") == path
            and labels.get("status") == status
        ):
            return value
    return 0.0


@pytest.mark.asyncio
async def test_successful_request_is_counted(client):
    before = _value("GET", "/health/live", "200")

    await client.get("/health/live")

    assert _value("GET", "/health/live", "200") == before + 1


@pytest.mark.asyncio
async def test_status_code_is_recorded(client, default_clinic):
    """Error rate is only computable if failures carry their status.

    Asserts the recorded status matches the response rather than hardcoding
    one: with no Authorization header at all this is a 401 from the security
    scheme, not the 403 the role check would produce.
    """
    res = await client.get(
        "/admin/phi-access", params={"clinic_id": default_clinic.id}
    )
    assert res.status_code >= 400

    recorded = _value("GET", "/admin/phi-access", str(res.status_code))
    assert recorded >= 1, (
        f"a {res.status_code} was not counted under that status label"
    )


@pytest.mark.asyncio
async def test_path_label_is_the_route_template_not_the_url(
    client, auth_doctor, patient_user
):
    """The cardinality guard: ids must never reach the label.

    One series per patient id would grow without bound and is the classic way
    a metrics endpoint takes down the monitoring it feeds.
    """
    await client.get(
        f"/patients/{patient_user.id}", headers=auth_doctor["headers"]
    )

    paths = {labels.get("path") for labels, _ in _samples()}

    assert not any(str(patient_user.id) in (p or "") for p in paths), (
        f"a raw id leaked into the path label: {paths}"
    )
    assert any("{" in (p or "") for p in paths), (
        "no templated route recorded — the label is not the route template"
    )


@pytest.mark.asyncio
async def test_unmatched_paths_collapse_into_one_series(client):
    """Scanners probe thousands of random URLs; each must not become a series."""
    for suffix in ("aaa", "bbb", "ccc", "ddd"):
        await client.get(f"/definitely-not-a-route-{suffix}")

    paths = [labels.get("path") for labels, _ in _samples()]

    assert "<unmatched>" in paths
    assert not any("definitely-not-a-route" in (p or "") for p in paths), (
        "unmatched URLs are being recorded verbatim — unbounded cardinality"
    )


@pytest.mark.asyncio
async def test_metric_is_exported_on_the_metrics_endpoint(client):
    """It has to actually reach Prometheus, not just exist in the registry."""
    await client.get("/health/live")

    exported = generate_latest().decode()

    assert "http_requests_total" in exported
    assert 'path="/health/live"' in exported


@pytest.mark.asyncio
async def test_error_rate_is_computable_from_the_counter(client, default_clinic):
    """The whole point: 5xx/total must be expressible from these labels."""
    await client.get("/health/live")
    await client.get("/admin/phi-access", params={"clinic_id": default_clinic.id})

    statuses = {labels.get("status") for labels, _ in _samples()}

    # At least one success and one failure class present and distinguishable.
    assert "200" in statuses
    assert any(s.startswith(("4", "5")) for s in statuses if s)
