from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    Integer,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.doctor import Doctor


class PrescriptionTemplate(Base):

    __tablename__ = "prescription_templates"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    doctor_id: Mapped[int] = mapped_column(
        ForeignKey(
            "doctors.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    clinic_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "clinics.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    doctor: Mapped["Doctor"] = relationship(
        "Doctor",
    )

    clinic = relationship(
        "Clinic",
    )

    items: Mapped[list["PrescriptionTemplateItem"]] = relationship(
        "PrescriptionTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
    )


class PrescriptionTemplateItem(Base):

    __tablename__ = "prescription_template_items"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    template_id: Mapped[int] = mapped_column(
        ForeignKey(
            "prescription_templates.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    medicine_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    dosage: Mapped[str | None] = mapped_column(
        String(100),
    )

    frequency: Mapped[str | None] = mapped_column(
        String(100),
    )

    duration_days: Mapped[int | None] = mapped_column(
        Integer,
    )

    instructions: Mapped[str | None] = mapped_column(
        Text,
    )

    template: Mapped["PrescriptionTemplate"] = relationship(
        "PrescriptionTemplate",
        back_populates="items",
    )