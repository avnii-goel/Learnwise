from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="learner")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    quiz_attempts = relationship(
        "QuizAttempt",
        back_populates="user",
        cascade="all, delete-orphan"
    )