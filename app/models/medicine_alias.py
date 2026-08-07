from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.medicine import Medicine

    
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base


class MedicineAlias(Base):
    __tablename__ = "medicine_aliases"

    __table_args__ = (
        UniqueConstraint(
            "medicine_id",
            "alias",
            name="uq_medicine_aliases_medicine_id_alias",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    medicine_id: Mapped[int] = mapped_column(
        ForeignKey(
            "medicines.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # Indexed because this is the lookup: the matcher resolves a typed name to
    # a medicine through here. Both indexes exist in the database already and
    # were simply never declared, so autogenerate wanted to drop them.
    alias: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )

    medicine: Mapped["Medicine"] = relationship(
        "Medicine",
        back_populates="aliases",
    )