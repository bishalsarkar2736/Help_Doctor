"""The active substance a brand contains.

Brands are what a prescriber types; generics are what a patient reacts to. The
catalogue has 11 brands of Cefixime, 7 of Metformin and 6 each of Diclofenac
and Esomeprazole, so without this relation a patient recorded as allergic to
"Cefixime" gets no warning when prescribed "Cefim" — the allergy check compares
brand-name strings and the two share no letters in common beyond a prefix.

medicines.generic_name is kept alongside the FK rather than dropped. It is
NOT NULL, is read by the AI context builder and the admin screens, and removing
it would be a wide change for no safety gain; the FK is what allergy checking
resolves through. If they ever disagree, generic_id is authoritative.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Generic(Base):

    __tablename__ = "generics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # As written on the packet, e.g. "Paracetamol + Caffeine". Unique so the
    # same substance cannot be entered twice under different rows and split a
    # brand family in half.
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    # Punctuation-stripped, lowercased, single-spaced — produced by
    # medicine_matcher_service.normalize(). Stored rather than computed on read
    # so lookups are an indexed equality test instead of a scan, and so
    # "Amoxicillin + Clavulanic Acid" and "amoxicillin clavulanic acid" resolve
    # to the same row.
    normalized_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    medicines = relationship("Medicine", back_populates="generic")

    def __repr__(self) -> str:
        return f"<Generic {self.name}>"
