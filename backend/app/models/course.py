from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    topics = relationship(
        "Topic",
        back_populates = "course",
        cascade = "all, delete-orphan"
    )

    quiz_attempts = relationship(
        "QuizAttempt",
        back_populates = "course",
        cascade = "all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("title", name="uq_courses_title"),
    )

