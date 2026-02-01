from sqlalchemy import String,Integer,ForeignKey,DateTime,func
from sqlalchemy.orm import Mapped,mapped_column,relationship

from app.db.base import Base

class Patient(Base):
    __tablename__ = "patients"

    id : Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id : Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id",ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    phone:Mapped[str] = mapped_column(String(20))
    address:Mapped[str] = mapped_column(String(255))
    date_of_birth : Mapped[str] = mapped_column(String(20))
    gender : Mapped[str] = mapped_column(String(10))

    created_at:Mapped[DateTime]= mapped_column(
        DateTime(timezone=True),server_default=func.now()
    )

    # back_populates MUST match User.patient
    user = relationship("User",back_populates="patients")