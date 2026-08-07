"""A superseded refresh token coming back ends its family.

Rotation already limited a stolen token's life to the owner's next refresh. It
did not NOTICE. Whoever lost that race saw a failed refresh, signed in again,
and the theft left no trace — the attacker simply tried again later.

Presenting an already-revoked token is the only evidence available, because a
client that rotates correctly never sends a superseded one twice. Which party
is the thief cannot be told apart from here, so both are made to
reauthenticate: the attacker cannot, the owner can.

TWO THINGS IT MUST NOT DO
Revoke more than the compromised login. Families are per-login, so a theft on
one device leaves the others alone.

Fire on an ordinary race. Two browser tabs waking together each hold the same
cookie and each refresh once, and the loser presents a token revoked moments
earlier. Signing someone out for using the product normally would make this
worse than the problem.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.limiter import limiter
from app.core.time import utc_now
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.security.auth_cookies import REFRESH_COOKIE_NAME
from app.security.jwt import hash_password
from app.security.tokens import hash_token


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
async def account(db):
    user = User(
        email="reuse-subject@example.com",
        full_name="Reuse Subject",
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
    res = await client.post(
        "/auth/login-json",
        json={"email": account["user"].email, "password": account["password"]},
    )
    assert res.status_code == 200, res.text

    token = client.cookies.get(REFRESH_COOKIE_NAME)
    client.cookies.clear()

    assert token
    return token


async def _refresh(client, token):
    client.cookies.clear()
    res = await client.post("/auth/refresh", json={"refresh_token": token})
    new = client.cookies.get(REFRESH_COOKIE_NAME)
    client.cookies.clear()
    return res, new


async def _age_revocation(db, token: str, delta: timedelta):
    """Move a revocation back in time, past the race window."""
    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(token)
        )
    )
    row.revoked_at = utc_now() - delta
    await db.commit()
    return row


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replaying_an_old_token_kills_the_current_one(
    client, db, account
):
    """The scenario: a thief copied the token, the owner refreshed first.

    Before this, the thief's replay simply failed and the owner carried on
    unaware. Now the replay ends the chain, so the stolen copy is worthless and
    the owner is asked to sign in again.
    """
    stolen = await _login(client, account)

    ok, current = await _refresh(client, stolen)
    assert ok.status_code == 200, ok.text
    assert current

    await _age_revocation(db, stolen, timedelta(minutes=5))

    replay, _ = await _refresh(client, stolen)
    assert replay.status_code == 401, "the superseded token was accepted"

    # The token the owner is holding is now dead too — that is the point.
    after, _ = await _refresh(client, current)
    assert after.status_code == 401, (
        "the live token survived a detected reuse of its own family"
    )


@pytest.mark.asyncio
async def test_the_whole_family_is_revoked_not_just_one_token(
    client, db, account
):
    stolen = await _login(client, account)

    ok, _ = await _refresh(client, stolen)
    assert ok.status_code == 200

    family = (
        await db.scalar(
            select(RefreshToken.family_id).where(
                RefreshToken.token_hash == hash_token(stolen)
            )
        )
    )

    await _age_revocation(db, stolen, timedelta(minutes=5))
    await _refresh(client, stolen)

    live = await db.scalar(
        select(func.count(RefreshToken.id)).where(
            RefreshToken.family_id == family,
            RefreshToken.revoked.is_(False),
        )
    )

    assert live == 0


@pytest.mark.asyncio
async def test_other_logins_are_untouched(client, db, account):
    """Proportionality. Being robbed on one device must not sign someone out
    of the workstation they are treating a patient at."""
    phone = await _login(client, account)
    workstation = await _login(client, account)

    ok, _ = await _refresh(client, phone)
    assert ok.status_code == 200

    await _age_revocation(db, phone, timedelta(minutes=5))
    await _refresh(client, phone)

    still_working, _ = await _refresh(client, workstation)

    assert still_working.status_code == 200, (
        "a theft on one device revoked an unrelated login"
    )


# ---------------------------------------------------------------------------
# What must NOT trigger it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_tabs_racing_does_not_sign_the_user_out(
    client, db, account
):
    """The false positive that would make this worse than the problem.

    Both tabs hold the same cookie and both refresh. The loser presents a
    token revoked a moment ago, which is a race rather than a theft, so the
    winner's session survives.
    """
    shared = await _login(client, account)

    first, winner = await _refresh(client, shared)
    assert first.status_code == 200

    # The second tab, immediately after — revoked_at is left as it is.
    loser, _ = await _refresh(client, shared)
    assert loser.status_code == 401, "the replay should still be refused"

    survives, _ = await _refresh(client, winner)

    assert survives.status_code == 200, (
        "a two-tab race revoked the user's live session"
    )


@pytest.mark.asyncio
async def test_an_invented_token_does_not_revoke_anything(client, db, account):
    """A string that was never a token says nothing about anybody."""
    live = await _login(client, account)

    bogus, _ = await _refresh(client, "not-a-real-token")
    assert bogus.status_code == 401

    ok, _ = await _refresh(client, live)

    assert ok.status_code == 200, "an invented token revoked a real session"


@pytest.mark.asyncio
async def test_an_expired_token_is_not_treated_as_reuse(client, db, account):
    """A session ending on schedule is not evidence of anything.

    The lookup that finds nothing filters on expiry as well as revocation, so
    without this distinction every naturally expired token would read as a
    replay.
    """
    first = await _login(client, account)
    second = await _login(client, account)

    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(first)
        )
    )
    row.expires_at = utc_now() - timedelta(days=1)
    await db.commit()

    expired, _ = await _refresh(client, first)
    assert expired.status_code == 401

    ok, _ = await _refresh(client, second)

    assert ok.status_code == 200, "an expired token was treated as a theft"


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotation_keeps_the_family(client, db, account):
    token = await _login(client, account)

    before = await db.scalar(
        select(RefreshToken.family_id).where(
            RefreshToken.token_hash == hash_token(token)
        )
    )

    ok, rotated = await _refresh(client, token)
    assert ok.status_code == 200

    after = await db.scalar(
        select(RefreshToken.family_id).where(
            RefreshToken.token_hash == hash_token(rotated)
        )
    )

    assert after == before


@pytest.mark.asyncio
async def test_each_login_starts_its_own_family(client, db, account):
    first = await _login(client, account)
    second = await _login(client, account)

    families = set(
        (
            await db.scalars(
                select(RefreshToken.family_id).where(
                    RefreshToken.token_hash.in_(
                        [hash_token(first), hash_token(second)]
                    )
                )
            )
        ).all()
    )

    assert len(families) == 2
