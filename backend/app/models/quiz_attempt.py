from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    quiz_type = Column(String(20), nullable=False, default="INITIAL") 
    score = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    responses = relationship("QuizResponse", back_populates="attempt", cascade="all, delete-orphan")
    user = relationship("User", back_populates="quiz_attempts")
    course = relationship("Course", back_populates="quiz_attempts")
    