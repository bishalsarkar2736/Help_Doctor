"""Other names for the same active substance.

MedicineAlias covers the brand: "Cefim-A" is another way of writing Cefim. It
cannot express that Acetaminophen and Paracetamol are the same substance,
because that fact belongs to the substance and not to any one of the brands
that contain it. Recording it per-brand would mean repeating it on every
Paracetamol product in the catalogue and losing it on the next one added.

This is what closes the gap for a patient whose allergy is recorded under a
name the catalogue does not use. "Acetaminophen" in an allergy field currently
matches nothing, because every brand of it is filed under Paracetamol.
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GenericAlias(Base):
    __tablename__ = "generic_aliases"

    __table_args__ = (
        # Uniqueness is on the NORMALISED form: "Acetaminophen" and
        # "acetaminophen" are the same claim, and storing both would leave the
        # allergy check doing the same comparison twice.
        UniqueConstraint(
            "generic_id",
            "normalized_alias",
            name="uq_generic_aliases_generic_id_normalized_alias",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    generic_id: Mapped[int] = mapped_column(
        ForeignKey("generics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # As entered, so it can be shown back to whoever registered it.
    alias: Mapped[str] = mapped_column(String(255), nullable=False)

    # The comparison key, stored rather than computed per query because the
    # allergy check reads this on every prescription.
    normalized_alias: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    generic = relationship("Generic", back_populates="aliases")
