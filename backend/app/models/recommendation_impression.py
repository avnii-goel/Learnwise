from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class RecommendationImpression(Base):
    __tablename__ = "recommendation_impressions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    resource_id = Column(
        Integer,
        ForeignKey("learning_resources.id", ondelete="CASCADE"),
        nullable=False
    )
    topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False
    )
    request_id = Column(UUID(as_uuid=True), nullable=False)
    strategy = Column(String(32), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    mastery_at_shown = Column(Float, nullable=True)
    components = Column(JSONB, nullable=False)
    reason = Column(Text, nullable=False)
    shown_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    clicked_at = Column(DateTime(timezone=True), nullable=True)
    is_synthetic = Column(Boolean, server_default=text("false"), default=False, nullable=False)

    user = relationship("User", back_populates="recommendation_impressions")
    resource = relationship("LearningResource", back_populates="impressions")
    topic = relationship("Topic", back_populates="recommendation_impressions")

    __table_args__ = (
        Index("ix_recommendation_impressions_user_shown", "user_id", "shown_at"),
        Index("ix_recommendation_impressions_resource", "resource_id"),
    )

