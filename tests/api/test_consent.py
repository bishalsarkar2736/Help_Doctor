"""Consent to the legal documents is recorded, versioned, and enforced.

The point of this feature is EVIDENCE. A test that only checked "registration
still works" would pass with no consent recorded at all, so the assertions here
are about what ends up in the database and what the server refuses.
"""

import pytest
from sqlalchemy import select

from app.core.limiter import limiter
from app.legal.documents import CURRENT_VERSIONS, LegalDocumentType
from app.models.user_consent import UserConsent

TERMS = CURRENT_VERSIONS[LegalDocumentType.TERMS]
PRIVACY = CURRENT_VERSIONS[LegalDocumentType.PRIVACY]
PASSWORD = "Sup3rSecret!pw"


@pytest.fixture(autouse=True)
def reset_limits():
    # /auth/register is capped at 5/minute and this file registers more often
    # than that; without a reset the later tests fail with 429s that look like
    # validation errors.
    limiter.reset()
    yield


def _payload(email: str, **overrides) -> dict:
    body = {
        "email": email,
        "full_name": "Consent Tester",
        "password": PASSWORD,
        "accepted_terms_version": TERMS,
        "accepted_privacy_version": PRIVACY,
    }
    body.update(overrides)
    return body


async def _consents(db, email: str) -> list[UserConsent]:
    from app.models.user import User

    user_id = await db.scalar(select(User.id).where(User.email == email))
    if user_id is None:
        return []

    return list(
        (
            await db.scalars(
                select(UserConsent).where(UserConsent.user_id == user_id)
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_versions_are_public(client):
    """The signup screen needs these before anyone has an account."""
    res = await client.get("/legal/documents")

    assert res.status_code == 200, res.text
    versions = res.json()["versions"]
    assert versions[LegalDocumentType.TERMS] == TERMS
    assert versions[LegalDocumentType.PRIVACY] == PRIVACY


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_records_both_consents(client, db):
    email = "consent.ok@example.com"

    res = await client.post("/auth/register", json=_payload(email))
    assert res.status_code == 201, res.text

    rows = await _consents(db, email)
    documents = {r.document: r.version for r in rows}

    assert documents == {
        LegalDocumentType.TERMS: TERMS,
        LegalDocumentType.PRIVACY: PRIVACY,
    }


@pytest.mark.asyncio
async def test_registration_without_consent_is_refused(client, db):
    """The account must not exist either — a half-done signup is the state
    this feature exists to prevent."""
    email = "consent.missing@example.com"
    body = _payload(email)
    del body["accepted_terms_version"]

    res = await client.post("/auth/register", json=body)
    assert res.status_code == 422, res.text

    assert await _consents(db, email) == []


@pytest.mark.asyncio
async def test_stale_version_is_refused(client, db):
    """Accepting an old version means being shown old wording.

    Recording that as consent to the CURRENT policy would put a false statement
    in the evidence, so it is rejected rather than silently upgraded.
    """
    email = "consent.stale@example.com"

    res = await client.post(
        "/auth/register",
        json=_payload(email, accepted_terms_version="1999-01-01"),
    )

    assert res.status_code == 400, res.text
    assert "updated" in res.text.lower()
    assert await _consents(db, email) == []


@pytest.mark.asyncio
async def test_no_account_is_created_when_consent_is_invalid(client, db):
    """Validation happens before the user row, so nothing is left behind."""
    from app.models.user import User

    email = "consent.norow@example.com"

    await client.post(
        "/auth/register",
        json=_payload(email, accepted_privacy_version="bogus"),
    )

    assert await db.scalar(select(User.id).where(User.email == email)) is None


@pytest.mark.asyncio
async def test_consent_captures_when_and_from_where(client, db):
    email = "consent.detail@example.com"

    res = await client.post(
        "/auth/register",
        json=_payload(email),
        headers={"User-Agent": "SmokeTest/1.0"},
    )
    assert res.status_code == 201, res.text

    rows = await _consents(db, email)
    assert rows
    for row in rows:
        assert row.accepted_at is not None
        assert row.user_agent == "SmokeTest/1.0"


@pytest.mark.asyncio
async def test_consent_is_audited(client, db):
    from app.models.audit_log import AuditLog

    email = "consent.audit@example.com"
    await client.post("/auth/register", json=_payload(email))

    entry = await db.scalar(
        select(AuditLog)
        .where(AuditLog.event_type == "consent", AuditLog.action == "accept")
        .order_by(AuditLog.id.desc())
    )

    assert entry is not None
    assert entry.details["accepted"][LegalDocumentType.TERMS] == TERMS


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_can_see_what_they_accepted(client, auth_admin):
    res = await client.get("/legal/consents", headers=auth_admin["headers"])

    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["current"]) == set(LegalDocumentType.ALL)
    assert "outdated" in body


@pytest.mark.asyncio
async def test_consents_endpoint_requires_authentication(client):
    res = await client.get("/legal/consents")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_the_same_version_twice_does_not_duplicate(
    db, auth_patient
):
    """A retried request must not read like two separate agreements."""
    from app.services.consent_service import record_consents

    accepted = {
        LegalDocumentType.TERMS: TERMS,
        LegalDocumentType.PRIVACY: PRIVACY,
    }

    await record_consents(db=db, user=auth_patient["user"], accepted=accepted)
    await record_consents(db=db, user=auth_patient["user"], accepted=accepted)
    await db.commit()

    rows = await db.scalars(
        select(UserConsent).where(
            UserConsent.user_id == auth_patient["user"].id,
            UserConsent.document == LegalDocumentType.TERMS,
        )
    )
    assert len(list(rows)) == 1
