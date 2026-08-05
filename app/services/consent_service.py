"""Recording acceptance of the legal documents."""

import logging

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.documents import LegalDocumentType, current_version, is_current
from app.models.user import User
from app.models.user_consent import UserConsent
from app.try_except.audit import log_audit_event
from app.try_except.exceptions import BadRequestError

logger = logging.getLogger(__name__)

# Truncated rather than rejected: a browser sending an oversized UA string is
# not a reason to refuse a signup, and the column is corroborating detail.
_MAX_USER_AGENT = 400


def _client_ip(request: Request) -> str | None:
    """The address the acceptance actually came from.

    request.client.host is the immediate peer, which behind the same-origin
    proxy is nginx — recording 172.x.x.x for every consent makes the field
    worthless as evidence.

    nginx sets X-Forwarded-For with `$proxy_add_x_forwarded_for`, which appends
    the peer it observed to whatever the client sent. So the LAST entry is
    nginx's own observation and is trustworthy; everything before it was
    supplied by the client and can be forged. Taking the last entry rather than
    the conventional first is deliberate for that reason — with one trusted
    proxy in front, it is the real client.

    If another proxy is ever added in front of nginx, this needs revisiting:
    the trustworthy entry moves by one hop per trusted proxy.
    """
    forwarded = request.headers.get("x-forwarded-for")

    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1][:45]

    return request.client.host if request.client else None


def validate_versions(accepted: dict[str, str]) -> None:
    """Refuse anything but the version currently published.

    A client submitting an older version has been shown older wording — or is
    replaying a stale form — and recording that as consent to the CURRENT
    policy would be a lie in the evidence. Fail loudly instead; the client
    refetches and shows the user what they are actually agreeing to.
    """
    for document in LegalDocumentType.ALL:
        supplied = accepted.get(document)

        if not supplied:
            raise BadRequestError(
                f"You must accept the {document} to continue."
            )

        if not is_current(document, supplied):
            raise BadRequestError(
                f"The {document} document has been updated. Please review the "
                "current version and accept it again."
            )


async def record_consents(
    *,
    db: AsyncSession,
    user: User,
    accepted: dict[str, str],
    request: Request | None = None,
) -> list[UserConsent]:
    """Write one row per document. Idempotent for the same version.

    Writes into the request's session so the consent and the account it belongs
    to commit together: an account created without its consent record, or a
    consent record for an account that failed to create, are both worse than
    failing the whole request.
    """
    ip = None
    agent = None

    if request is not None:
        ip = _client_ip(request)
        agent = (request.headers.get("user-agent") or "")[:_MAX_USER_AGENT] or None

    recorded: list[UserConsent] = []

    for document in LegalDocumentType.ALL:
        version = accepted[document]

        existing = await db.scalar(
            select(UserConsent).where(
                UserConsent.user_id == user.id,
                UserConsent.document == document,
                UserConsent.version == version,
            )
        )

        if existing is not None:
            # A retried or double-submitted request must not create a second
            # row that reads like a separate agreement.
            recorded.append(existing)
            continue

        consent = UserConsent(
            user_id=user.id,
            document=document,
            version=version,
            ip_address=ip,
            user_agent=agent,
        )
        db.add(consent)
        recorded.append(consent)

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="consent",
        action="accept",
        user_id=user.id,
        resource="legal_documents",
        details={
            "accepted": {d: accepted[d] for d in LegalDocumentType.ALL},
            "ip_address": ip,
        },
    )

    return recorded


async def consents_for(
    *, db: AsyncSession, user_id: int
) -> dict[str, str | None]:
    """Latest accepted version per document, for display and for support."""
    rows = (
        await db.execute(
            select(UserConsent.document, UserConsent.version)
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.accepted_at.desc())
        )
    ).all()

    latest: dict[str, str | None] = {d: None for d in LegalDocumentType.ALL}

    for document, version in rows:
        if latest.get(document) is None:
            latest[document] = version

    return latest


def current_documents() -> dict[str, str]:
    return {d: current_version(d) for d in LegalDocumentType.ALL}
