"""The legal documents users must accept, and their current versions.

Versions live in code rather than the database on purpose. The version and the
TEXT have to change together — a version number pointing at wording nobody can
reproduce is not evidence of anything — and code is what gets reviewed,
deployed and tagged as a unit. The database records WHO accepted WHICH version;
this module is the source of truth for what that version was.

PUBLISHING A NEW VERSION
------------------------
1. Update the document text in the frontend (src/pages/legal/).
2. Bump the version here, in the same commit as the text.
3. Deploy.

Bumping the version does NOT currently force existing users to re-accept —
registration and invitation acceptance are the only points consent is
collected. If a change is material enough to need re-consent from people
already using the system, that is a follow-up (a consent_required flag on
/users/me and a blocking prompt), not something this module does today. Said
plainly here so nobody assumes a version bump is doing more than it is.

Dates, not sequence numbers: "2026-08-01" is directly comparable to a signed
copy and to a git tag, whereas "v3" tells an auditor nothing about when it took
effect.
"""

from typing import Final


class LegalDocumentType:
    """Kept as constants, not an Enum, so stored values stay stable strings."""

    TERMS: Final = "terms"
    PRIVACY: Final = "privacy"

    ALL: Final = (TERMS, PRIVACY)


# Bump these ONLY together with the corresponding document text.
CURRENT_VERSIONS: Final[dict[str, str]] = {
    LegalDocumentType.TERMS: "2026-08-01",
    LegalDocumentType.PRIVACY: "2026-08-01",
}


def current_version(document: str) -> str:
    try:
        return CURRENT_VERSIONS[document]
    except KeyError:
        raise ValueError(f"unknown legal document: {document!r}")


def is_current(document: str, version: str) -> bool:
    return current_version(document) == version
