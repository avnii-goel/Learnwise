from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class AdaptiveQuizStep(Base):
    __tablename__ = "adaptive_quiz_steps"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(
        Integer,
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number = Column(Integer, nullable=False)
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_difficulty = Column(String(16), nullable=False)
    served_difficulty = Column(String(16), nullable=False)
    selection_reason = Column(String(32), nullable=False)
    mastery_before = Column(Float, nullable=False)
    mastery_after = Column(Float, nullable=True)
    selected_answer = Column(String(1), nullable=True)
    is_correct = Column(Boolean, nullable=True)
    served_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    answered_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("attempt_id", "step_number", name="uq_adaptive_steps_attempt_step"),
        UniqueConstraint("attempt_id", "question_id", name="uq_adaptive_steps_attempt_question"),
    )

    attempt = relationship("QuizAttempt", back_populates="adaptive_steps")
    question = relationship("Question", back_populates="adaptive_steps")

