from sqlalchemy import (
    Integer, DateTime,Boolean, String, Text, func
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

    # server_default is REQUIRED here, not decorative. The column is NOT NULL
    # and the database already defaults it to CURRENT_TIMESTAMP, but without
    # this the mapper does not know that: it sends an explicit NULL and every
    # ORM insert fails. POST /admin/medicines returned 500 for exactly this
    # reason — an admin could not add a medicine at all.
    #
    # The seeder was unaffected because it uses a Core insert() with an
    # explicit values dict, which omits the column and lets the DB default
    # apply. That is why the bug survived a successful 320-row seed.
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    aliases = relationship(
        "MedicineAlias",
        back_populates="medicine",
        cascade="all, delete-orphan",
        lazy="selectin",
    )