"""Refresh tokens are never stored in a form that can be replayed.

A refresh token is a credential: presenting it returns a working access token
for its owner, for up to REFRESH_TOKEN_EXPIRE_DAYS. Stored as-is, anything that
could read the table — a backup, a replica, a support query, an injection —
held live sessions for every signed-in user and could keep renewing them.

Password reset tokens, email verification tokens and invitations were already
hashed. Refresh tokens were the one member of that family still kept in the
clear, and the longest-lived of the four.

These assert the property rather than the mechanism: what must be true is that
the value the client holds cannot be recovered from the database, and that
everything built on refresh tokens still works.
"""

import pytest
from sqlalchemy import inspect, select, text

from app.core.limiter import limiter
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.security.auth_cookies import REFRESH_COOKIE_NAME
from app.security.jwt import hash_password
from app.security.tokens import hash_token


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Auth endpoints allow a handful of calls a minute, and slowapi keeps its
    counters in process memory. Without this, logging in repeatedly across
    tests produces 429s that look like failures of the thing being tested."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
async def account(db):
    user = User(
        email="refresh-subject@example.com",
        full_name="Refresh Subject",
        hashed_password=hash_password("Correct-Horse-9"),
        role=UserRole.PATIENT,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    await db.commit()

    return {"user": user, "password": "Correct-Horse-9"}


async def _login(client, account) -> str:
    """Returns the refresh token, which arrives as an httpOnly cookie.

    The login body deliberately carries refresh_token: None — the credential
    is not exposed to JavaScript. Reading it from the response body, as the
    first version of these tests did, silently yields None and every
    assertion downstream tests nothing.
    """
    res = await client.post(
        "/auth/login-json",
        json={"email": account["user"].email, "password": account["password"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["refresh_token"] is None, (
        "the refresh token must not be returned in the body"
    )

    refresh = client.cookies.get(REFRESH_COOKIE_NAME)
    assert refresh, "no refresh cookie was set"

    return refresh


# ---------------------------------------------------------------------------
# The property
# ---------------------------------------------------------------------------


def test_the_table_has_no_plaintext_column():
    """Structural. A column that does not exist cannot be leaked."""
    columns = {c.key for c in inspect(RefreshToken).columns}

    assert "token" not in columns
    assert "token_hash" in columns


@pytest.mark.asyncio
async def test_the_issued_token_does_not_appear_anywhere_in_the_row(
    client, db, account
):
    """The check that would have caught this: search the stored row for the
    value the client was given."""
    refresh = await _login(client, account)

    row = await db.scalar(
        select(RefreshToken).order_by(RefreshToken.id.desc())
    )

    assert refresh not in str(row.token_hash)
    assert row.token_hash == hash_token(refresh)


@pytest.mark.asyncio
async def test_the_raw_token_is_not_recoverable_from_the_table(
    client, db, account
):
    """Asserted against the database itself rather than the ORM, because a
    dump is how this would actually escape."""
    refresh = await _login(client, account)

    found = await db.scalar(
        text("SELECT count(*) FROM refresh_tokens WHERE token_hash = :t"),
        {"t": refresh},
    )

    assert found == 0, "the plaintext token matched a stored value"


# ---------------------------------------------------------------------------
# Everything built on refresh tokens still works
#
# read_refresh_token prefers the COOKIE over the body, so a test that supplies
# a token in the body while a cookie is still set is exercising the cookie and
# proving nothing. Anything asserting on a specific supplied value clears the
# jar first.
# ---------------------------------------------------------------------------


def _forget_cookie(client):
    client.cookies.clear()


@pytest.mark.asyncio
async def test_a_refresh_token_can_still_be_redeemed(client, account):
    refresh = await _login(client, account)
    _forget_cookie(client)

    res = await client.post("/auth/refresh", json={"refresh_token": refresh})

    assert res.status_code == 200, res.text
    assert res.json()["access_token"]


@pytest.mark.asyncio
async def test_rotation_still_invalidates_the_old_token(client, account):
    """The security property that already existed and must survive the change."""
    first = await _login(client, account)

    rotated = await client.post("/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200, rotated.text

    second = client.cookies.get(REFRESH_COOKIE_NAME)
    assert second and second != first, "rotation did not issue a new token"

    _forget_cookie(client)

    replay = await client.post("/auth/refresh", json={"refresh_token": first})

    assert replay.status_code == 401, "the superseded token still worked"


@pytest.mark.asyncio
async def test_an_invented_token_is_rejected(client, account):
    await _login(client, account)
    _forget_cookie(client)

    res = await client.post(
        "/auth/refresh", json={"refresh_token": "not-a-real-token"}
    )

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_a_stored_digest_cannot_be_presented_as_a_token(
    client, db, account
):
    """The failure mode a naive fix invites.

    If the lookup compared the presented value to the stored column directly,
    anyone holding a database dump could authenticate with the digest itself —
    the leak this change exists to close, reopened.
    """
    await _login(client, account)

    row = await db.scalar(select(RefreshToken).order_by(RefreshToken.id.desc()))

    _forget_cookie(client)

    res = await client.post(
        "/auth/refresh", json={"refresh_token": row.token_hash}
    )

    assert res.status_code == 401, "the stored digest worked as a credential"


@pytest.mark.asyncio
async def test_logout_still_revokes(client, account):
    refresh = await _login(client, account)

    out = await client.post("/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 200, out.text

    _forget_cookie(client)

    res = await client.post("/auth/refresh", json={"refresh_token": refresh})

    assert res.status_code == 401, "a logged-out token was still redeemable"


@pytest.mark.asyncio
async def test_two_logins_produce_two_distinct_rows(client, db, account):
    """Digests collide only if the tokens do, so unique=True on the hash must
    not merge independent sessions."""
    first = await _login(client, account)
    _forget_cookie(client)
    second = await _login(client, account)

    assert first != second

    rows = (
        await db.scalars(
            select(RefreshToken).where(
                RefreshToken.token_hash.in_(
                    [hash_token(first), hash_token(second)]
                )
            )
        )
    ).all()

    assert len(rows) == 2
