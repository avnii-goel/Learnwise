from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base

ALLOWED_RESOURCE_TYPES = {"article", "video", "tutorial", "documentation"}


class LearningResource(Base):
    __tablename__ = "learning_resources"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False
    )
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    resource_type = Column(String(50), nullable=False)
    url = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False, default=1)
    difficulty = Column(String(20), nullable=False, default="medium")
    embedding = Column(Vector(384), nullable=True)
    embedding_hash = Column(Text, nullable=True)

    topic = relationship("Topic", back_populates="resources")
    impressions = relationship(
        "RecommendationImpression",
        back_populates="resource",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("topic_id", "url", name="uq_learning_resources_topic_url"),
    )
