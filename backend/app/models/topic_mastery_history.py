from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TopicMasteryHistory(Base):
    __tablename__ = "topic_mastery_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False
    )
    attempt_id = Column(
        Integer,
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False
    )
    mastery_before = Column(Float, nullable=False)
    mastery_after = Column(Float, nullable=False)
    answers_in_attempt = Column(Integer, nullable=False)
    correct_in_attempt = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    topic = relationship("Topic")
    attempt = relationship("QuizAttempt")

    __table_args__ = (
        UniqueConstraint("attempt_id", "topic_id", name="uq_topic_mastery_history_attempt_topic"),
        Index("ix_topic_mastery_history_user_topic_created", "user_id", "topic_id", "created_at"),
    )
