from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(
        Integer, 
        ForeignKey("topics.id", ondelete = "CASCADE"),
        nullable = False
    )
    question_text = Column(Text, nullable=False)

    option_a = Column(String(500), nullable=False)
    option_b = Column(String(500), nullable=False)
    option_c = Column(String(500), nullable=False)
    option_d = Column(String(500), nullable=False)

    correct_answer = Column(String(1), nullable=False)
    difficulty = Column(String(20), nullable=False, default = "Medium")

    topic = relationship("Topic", back_populates="questions")
    responses = relationship("QuizResponse", back_populates = "question")

    __table_args__ = (
        UniqueConstraint("topic_id", "question_text", name="uq_questions_topic_id_question_text"),
    )