# from datetime import datetime
# from sqlalchemy import BigInteger, String, Text, Boolean, DateTime, ForeignKey
# from sqlalchemy.orm import Mapped, mapped_column
# from app.core.time import UTC
# from app.db.base import Base


# class AppointmentAuditLog(Base):
#     __tablename__ = "appointment_audit_log"

#     id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

#     appointment_id: Mapped[int] = mapped_column(
#         BigInteger,
#         ForeignKey("appointments.id", ondelete="CASCADE"),
#         nullable=False,
#     )

#     from_status: Mapped[str] = mapped_column(String(32), nullable=False)
#     to_status: Mapped[str] = mapped_column(String(32), nullable=False)

#     changed_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

#     actor_role: Mapped[str] = mapped_column(String(16), nullable=False)

#     is_idempotent: Mapped[bool] = mapped_column(
#         Boolean,
#         default=False,
#         nullable=False,
#     )

#     created_at: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True),
#         default=datetime.now(UTC),
#         nullable=False,
#     )
