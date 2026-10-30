from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(
        Integer, 
        ForeignKey("courses.id", ondelete = "CASCADE"),
        nullable = False
    )
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, nullable=False, default= 1)

    course = relationship("Course", back_populates="topics")

    resources = relationship(
        "LearningResource",
        back_populates = "topic",
        cascade = "all, delete-orphan"
    )

    questions = relationship(
        "Question",
        back_populates = "topic",
        cascade = "all, delete-orphan"
    )

    responses = relationship(
        "QuizResponse",
        back_populates = "topic"
    )

    masteries = relationship(
        "TopicMastery",
        back_populates = "topic",
        cascade = "all, delete-orphan"
    )

    prerequisites = relationship(
        "TopicPrerequisite",
        foreign_keys="TopicPrerequisite.topic_id",
        back_populates="topic",
        cascade="all, delete-orphan"
    )

    prerequisite_for = relationship(
        "TopicPrerequisite",
        foreign_keys="TopicPrerequisite.prerequisite_topic_id",
        back_populates="prerequisite_topic",
        cascade="all, delete-orphan"
    )

    recommendation_impressions = relationship(
        "RecommendationImpression",
        back_populates="topic",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("course_id", "title", name="uq_topics_course_id_title"),
    )