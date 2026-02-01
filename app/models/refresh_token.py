from sqlalchemy import Column,Integer,String,DateTime,Boolean,ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.postgres import Base
from sqlalchemy.sql import func

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String,unique=True,index=True,nullable=False)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    user = relationship("User", back_populates="refresh_tokens")

    revoked = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


    def __repr__(self):
        return f"<RefreshToken user_id={self.user_id} revoked={self.revoked}>"
