from sqlalchemy import Column, Integer, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class TopicPrerequisite(Base):
    __tablename__ = "topic_prerequisites"

    topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False
    )
    prerequisite_topic_id = Column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False
    )

    topic = relationship(
        "Topic",
        foreign_keys=[topic_id],
        back_populates="prerequisites"
    )
    prerequisite_topic = relationship(
        "Topic",
        foreign_keys=[prerequisite_topic_id],
        back_populates="prerequisite_for"
    )

    __table_args__ = (
        CheckConstraint("topic_id <> prerequisite_topic_id", name="chk_topic_prerequisites_no_self"),
    )

