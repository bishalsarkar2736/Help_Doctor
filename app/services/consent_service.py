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
from app.utils.request_ip import client_ip_from

logger = logging.getLogger(__name__)

# Truncated rather than rejected: a browser sending an oversized UA string is
# not a reason to refuse a signup, and the column is corroborating detail.
_MAX_USER_AGENT = 400

# Matches UserConsent.ip_address, String(45) — the widest an IPv6 address with
# an embedded IPv4 suffix and a zone index can be.
_MAX_IP_ADDRESS = 45


def _client_ip(request: Request) -> str | None:
    """The address the acceptance actually came from.

    request.client.host is the immediate peer, which behind a proxy is the
    proxy — recording 172.x.x.x for every consent makes the field worthless as
    evidence.

    Delegates to the shared resolver rather than reading X-Forwarded-For here.
    This function used to take the LAST entry of the header, which is correct
    with EXACTLY ONE trusted proxy appending via `$proxy_add_x_forwarded_for`
    and wrong with any other number: its own docstring said so, and adding a TLS
    terminator in front of nginx makes it two, at which point the last entry is
    nginx's address and every consent record would name an internal host.

    It also believed the header whoever connected, so a caller reaching the API
    directly could put any address into a legal record. client_ip_from reads it
    only when the peer is a configured trusted proxy and walks the chain from
    the right past each one, so it is correct for any number of hops and
    forgeable at none.

    Returns None rather than the resolver's "unknown" sentinel: the column is
    nullable, and NULL says "not recorded" where a literal string would read as
    a value that was.
    """
    ip = client_ip_from(request)

    if not ip or ip == "unknown":
        return None

    return ip[:_MAX_IP_ADDRESS]


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
