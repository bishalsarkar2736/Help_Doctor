"""Patient search is rate limited, per user rather than per address.

The endpoint returns identifying details for a clinic's whole roster, twenty
rows at a time, and nothing capped how fast it could be asked. Clinic scoping
bounds WHO can be reached; a limit bounds HOW FAST, which is what makes bulk
extraction slow and visible rather than a single loop.

WHY NOT THE DEFAULT IP KEY
The limiter keys on the client address everywhere else, which is right for
public endpoints where the caller has no other identity. Here it is wrong in
both directions: a clinic sits behind one office connection, so an IP limit
throttles a whole front desk together, while a stolen token used from anywhere
else gets a full budget of its own — the case the limit exists for.

THE NUMBER DEPENDS ON THE FRONTEND
Search runs on every keystroke. Undebounced, a 13-character name was 12
requests, so any limit tight enough to matter would have fired during ordinary
typing. The debounce added alongside this is what makes 60/minute both
generous for a person and tight for a script.
"""

import pytest

from app.core.limiter import authenticated_key, limiter
from app.security.jwt import create_access_token


@pytest.fixture(autouse=True)
def _reset_limiter():
    """slowapi keeps counters in process memory; leaking them between tests
    makes results depend on execution order."""
    limiter.reset()
    yield
    limiter.reset()


class _Request:
    """Enough of a Request for the key function."""

    def __init__(self, headers=None, host="203.0.113.7"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()
        self.scope = {"client": (host, 0), "headers": []}


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------


def test_the_key_is_the_authenticated_user():
    token = create_access_token(data={"sub": "42", "role": "receptionist"})

    key = authenticated_key(_Request({"Authorization": f"Bearer {token}"}))

    assert key == "user:42"


def test_two_users_on_one_address_get_separate_budgets():
    """The front-desk case: several staff behind one office connection."""
    keys = {
        authenticated_key(
            _Request(
                {"Authorization": f"Bearer {create_access_token(
                    data={'sub': str(uid), 'role': 'receptionist'})}"},
                host="203.0.113.7",
            )
        )
        for uid in (1, 2, 3)
    }

    assert len(keys) == 3


def test_one_user_from_two_addresses_shares_a_budget():
    """A stolen token does not get a fresh allowance by moving."""
    token = create_access_token(data={"sub": "42", "role": "receptionist"})
    header = {"Authorization": f"Bearer {token}"}

    assert authenticated_key(_Request(header, host="203.0.113.7")) == (
        authenticated_key(_Request(header, host="198.51.100.9"))
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ],
)
def test_an_unusable_token_falls_back_to_the_address(headers):
    """Not an authentication decision — the endpoint's own dependency rejects
    a bad token. This only needs something stable to count against, so it must
    never raise."""
    assert authenticated_key(_Request(headers)) == "203.0.113.7"


# ---------------------------------------------------------------------------
# The limit, through the endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordinary_use_is_not_throttled(client, auth_receptionist):
    """A handful of searches in a row must simply work.

    The point of the debounce is that this is what real use looks like.
    """
    for _ in range(10):
        res = await client.get(
            "/patients/search",
            params={"q": "john"},
            headers=auth_receptionist["headers"],
        )

        assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_a_burst_is_eventually_refused(client, auth_receptionist):
    """Past the budget the endpoint stops answering rather than slowing down."""
    statuses = []

    for _ in range(75):
        res = await client.get(
            "/patients/search",
            params={"q": "john"},
            headers=auth_receptionist["headers"],
        )
        statuses.append(res.status_code)

    assert 429 in statuses, "the limit never fired"
    assert statuses[0] == 200, "it fired immediately, which would break the desk"
    assert statuses.count(200) >= 60, (
        f"refused after only {statuses.count(200)} requests — too tight for a "
        f"busy front desk"
    )


@pytest.mark.asyncio
async def test_one_user_hitting_the_limit_does_not_block_another(
    client, db, auth_receptionist, default_clinic
):
    """The reason for keying on the user: a colleague at the same desk keeps
    working."""
    from app.models.user import User, UserRole

    for _ in range(75):
        await client.get(
            "/patients/search",
            params={"q": "john"},
            headers=auth_receptionist["headers"],
        )

    colleague = User(
        email="colleague@example.com", full_name="Colleague",
        hashed_password="x", role=UserRole.RECEPTIONIST, is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(colleague)
    await db.flush()
    await db.commit()

    token = create_access_token(
        data={"sub": str(colleague.id), "role": UserRole.RECEPTIONIST.value}
    )

    res = await client.get(
        "/patients/search",
        params={"q": "john"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200, res.text
