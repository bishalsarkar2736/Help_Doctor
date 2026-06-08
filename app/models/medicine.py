from sqlalchemy import (
    Integer, DateTime,Boolean, String, Text
)
from sqlalchemy.orm import  mapped_column,relationship

from app.db.base import Base



class Medicine(Base):

    __tablename__ = "medicines"

    id = mapped_column(
        Integer,
        primary_key=True,
    )

    name = mapped_column(
        String(255),
        unique=True,
        index=True,
    )

    generic_name = mapped_column(
        String(255),
        nullable=False,
    )

    strength = mapped_column(
        String(100),
        nullable=True,
    )

    manufacturer = mapped_column(
        String(255),
        nullable=False,
    )

    category = mapped_column(
        String(100),
        nullable=True,
    )

    dosage_form = mapped_column(
        String(100),
        nullable=True,
    )

    common_use = mapped_column(
        Text,
        nullable=True,
    )

    common_side_effects = mapped_column(
        Text,
        nullable=True,
    )

    storage_guidance = mapped_column(
        Text,
        nullable=True,
    )

    is_brand = mapped_column(
        Boolean,
        default=True,
    )

    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    aliases = relationship(
        "MedicineAlias",
        back_populates="medicine",
        cascade="all, delete-orphan",
        lazy="selectin",
    )