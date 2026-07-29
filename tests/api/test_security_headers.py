import pytest


@pytest.mark.asyncio
async def test_security_headers_on_api_response(client):
    res = await client.get("/doctors")
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    # Strict CSP is applied to API (JSON) responses.
    assert res.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


@pytest.mark.asyncio
async def test_hsts_not_sent_over_plain_http(client):
    # Sending HSTS over http:// is meaningless (RFC 6797) and poisons browsers
    # in development — it pins localhost to HTTPS, breaking the frontend.
    res = await client.get("/doctors")
    assert "Strict-Transport-Security" not in res.headers


@pytest.mark.asyncio
async def test_hsts_sent_when_proxy_reports_https(client):
    res = await client.get("/doctors", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in res.headers


@pytest.mark.asyncio
async def test_csp_exempt_on_docs(client):
    # The OpenAPI schema / Swagger UI must not carry the strict CSP.
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    assert "Content-Security-Policy" not in res.headers
