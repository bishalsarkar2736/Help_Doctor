"""Refresh tokens, stored as hashes.

A refresh token IS a credential: presenting it returns a working access token
for its owner, for up to REFRESH_TOKEN_EXPIRE_DAYS. Storing the value itself
meant anything that could read the table — a backup, a replica, a support
query, an injection — held live sessions for every signed-in user, and the
holder could keep renewing them indefinitely.

Hashed here for the same reason password reset tokens, email verification
tokens and invitations already are: the server never needs the original, only
the ability to recognise it. Refresh tokens were the one member of that family
still kept in the clear, and the longest-lived of the four.

SHA-256 rather than argon2, matching app/security/tokens.py. These are 32 bytes
from a CSPRNG, not a password: there is no dictionary to attack and nothing to
slow down, so a fast digest is the right tool and lets the lookup stay a single
indexed equality.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)

    # SHA-256 hex digest of the token handed to the client. The plaintext
    # exists only in the response that created it and in the client's storage.
    token_hash = Column(String(64), unique=True, index=True, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user = relationship("User", back_populates="refresh_tokens")

    revoked = Column(Boolean, default=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        # Deliberately no token material, hashed or otherwise: repr lands in
        # logs and debuggers.
        return f"<RefreshToken user_id={self.user_id} revoked={self.revoked}>"
