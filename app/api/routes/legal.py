"""Current legal document versions, and what the signed-in user accepted.

Public and unauthenticated: the registration and invitation-acceptance screens
need the current versions BEFORE anyone has an account, and they must submit
exactly what they were shown.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.user import User
from app.security.jwt import get_current_user
from app.services.consent_service import consents_for, current_documents

router = APIRouter(prefix="/legal", tags=["Legal"])


@router.get("/documents")
async def get_documents() -> dict:
    """The versions a client must submit when collecting acceptance.

    Clients should fetch this immediately before showing the consent control
    rather than hardcoding a version — the server refuses anything but the
    current one, so a stale hardcoded value fails every signup after a policy
    update.
    """
    return {"versions": current_documents()}


@router.get("/consents")
async def get_my_consents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """What this user has accepted, and whether it is still current.

    `outdated` is informational today: nothing blocks a user whose accepted
    version has since been superseded. Making it blocking is a deliberate
    follow-up, not an oversight — see app/legal/documents.py.
    """
    accepted = await consents_for(db=db, user_id=current_user.id)
    current = current_documents()

    return {
        "accepted": accepted,
        "current": current,
        "outdated": [
            document
            for document, version in accepted.items()
            if version != current.get(document)
        ],
    }
