from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    quiz_type = Column(String(20), nullable=False, default="INITIAL")
    mode = Column(String(16), nullable=False, default="fixed")
    status = Column(String(16), nullable=False, default="completed")
    score = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("mode IN ('fixed', 'adaptive')", name="chk_quiz_attempts_mode"),
        CheckConstraint("status IN ('in_progress', 'completed')", name="chk_quiz_attempts_status"),
    )

    responses = relationship("QuizResponse", back_populates="attempt", cascade="all, delete-orphan")
    adaptive_steps = relationship(
        "AdaptiveQuizStep",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="AdaptiveQuizStep.step_number",
    )
    user = relationship("User", back_populates="quiz_attempts")
    course = relationship("Course", back_populates="quiz_attempts")
    topic = relationship("Topic", back_populates="quiz_attempts")
