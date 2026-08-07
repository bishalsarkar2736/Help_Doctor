"""The refresh token must leave JavaScript's reach.

It is the PERSISTENT credential: an access token stolen through XSS expires in
minutes and cannot be renewed, while a stolen refresh token is an account
indefinitely, and nothing in the audit trail separates the thief from the real
user.

The load-bearing assertions here are the negative ones — that the token is
absent from the response body, and that the cookie carries HttpOnly. A test
that only checked "refresh still works" would pass just as happily with the
token sitting in localStorage.
"""

import pytest
from sqlalchemy import select

from app.core.limiter import limiter
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.security.auth_cookies import REFRESH_COOKIE_NAME
from app.security.jwt import hash_password

PASSWORD = "Sup3rSecret!pw"


@pytest.fixture(autouse=True)
def isolate_session(client):
    """Start every test with an empty cookie jar and a fresh rate-limit window.

    Two shared pieces of state bite here, and both make tests pass alone and
    fail in a group:

    * the client's cookie jar persists, so a revoked cookie from an earlier
      test makes the next refresh 401;
    * /auth/login is capped at 5/minute per client address, and this file logs
      in far more often than that — later logins return 429, no session is
      established, and the failure looks like a broken cookie rather than a
      throttled login.

    The limiter is reset rather than disabled, so the production configuration
    is still the one under test everywhere else.
    """
    client.cookies.clear()
    limiter.reset()
    yield
    client.cookies.clear()


@pytest.fixture
async def account(db):
    user = User(
        email="cookie.user@example.com",
        hashed_password=hash_password(PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client, account):
    return await client.post(
        "/auth/login",
        data={"username": account.email, "password": PASSWORD},
    )


def _set_cookie_header(res) -> str:
    raw = res.headers.get_list("set-cookie")
    return next((h for h in raw if h.startswith(f"{REFRESH_COOKIE_NAME}=")), "")


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sets_the_refresh_cookie(client, account):
    res = await _login(client, account)

    assert res.status_code == 200, res.text
    assert res.cookies.get(REFRESH_COOKIE_NAME), "no refresh cookie was set"


@pytest.mark.asyncio
async def test_login_does_not_return_the_refresh_token_in_the_body(
    client, account
):
    """The point of the change. Returning it hands it straight to JS."""
    res = await _login(client, account)

    assert res.json().get("refresh_token") is None
    # And it must not be smuggled in under another key either.
    cookie_value = res.cookies.get(REFRESH_COOKIE_NAME)
    assert cookie_value not in res.text


@pytest.mark.asyncio
async def test_cookie_is_httponly_and_samesite_strict(client, account):
    res = await _login(client, account)
    header = _set_cookie_header(res).lower()

    assert "httponly" in header, "cookie is readable by document.cookie"
    assert "samesite=strict" in header, "cookie would ride cross-site requests"
    # Path must stay "/" — the SPA reaches the API at /api/auth/... through the
    # same-origin proxy, so a cookie scoped to /auth would never be sent back.
    assert "path=/" in header


@pytest.mark.asyncio
async def test_access_token_is_still_returned(client, account):
    """Only the refresh token moved; the Authorization header flow is intact."""
    res = await _login(client, account)
    assert res.json()["access_token"]


# ---------------------------------------------------------------------------
# Redeeming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_works_with_the_cookie_and_no_body(client, account):
    await _login(client, account)

    res = await client.post("/auth/refresh")

    assert res.status_code == 200, res.text
    assert res.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_rotates_the_cookie(client, account):
    """Rotation is single-use, so the cookie must be replaced on every refresh.

    Leaving the old value would send an already-revoked token next time and
    log the user out at random.
    """
    login = await _login(client, account)
    first = login.cookies.get(REFRESH_COOKIE_NAME)

    res = await client.post("/auth/refresh")
    second = res.cookies.get(REFRESH_COOKIE_NAME)

    assert second, "refresh did not set a new cookie"
    assert second != first, "the revoked token was left in the cookie"


@pytest.mark.asyncio
async def test_refresh_without_cookie_or_body_is_refused(client):
    res = await client.post("/auth/refresh")
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_refresh_still_accepts_a_body_token(client, db, account):
    """Transition path: sessions issued before this change kept the token in
    localStorage, and must be able to redeem it once."""
    await _login(client, account)

    # Taken from the cookie, not from the database: refresh tokens are stored
    # as digests now, so the plaintext cannot be read back. That is the point
    # of the change, and this test only ever needed A valid token — the one
    # the client was actually issued.
    token = client.cookies.get(REFRESH_COOKIE_NAME)
    assert token, "no refresh cookie was set"

    client.cookies.clear()

    res = await client.post("/auth/refresh", json={"refresh_token": token})
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Ending the session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_revokes_the_token_and_clears_the_cookie(
    client, db, account
):
    await _login(client, account)

    res = await client.post("/auth/logout", json={})
    assert res.status_code == 200, res.text

    # Cookie cleared on the response...
    header = _set_cookie_header(res)
    assert 'refresh_token=""' in header or "refresh_token=;" in header

    # ...and the token is dead server-side, so a stolen copy is useless.
    live = await db.scalar(
        select(RefreshToken.id).where(
            RefreshToken.user_id == account.id,
            RefreshToken.revoked.is_(False),
        )
    )
    assert live is None


@pytest.mark.asyncio
async def test_refresh_after_logout_is_refused(client, account):
    await _login(client, account)
    await client.post("/auth/logout", json={})

    res = await client.post("/auth/refresh")
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_logout_without_a_session_still_succeeds(client):
    """A browser holding a stale cookie must still end up logged out."""
    res = await client.post("/auth/logout", json={})
    assert res.status_code == 200, res.text
