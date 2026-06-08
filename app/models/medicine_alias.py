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
    )

    alias: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    medicine: Mapped["Medicine"] = relationship(
        "Medicine",
        back_populates="aliases",
    )