from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TopicMasteryItemResponse(BaseModel):
    course_id: int
    course_title: str
    topic_id: int
    topic_title: str
    order: int
    mastery_probability: float | None = None
    status: str
    total_answers: int = 0
    correct_answers: int = 0
    last_answered_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CourseMasterySummary(BaseModel):
    total_topics: int
    not_attempted: int
    weak: int
    developing: int
    strong: int
    average_mastery_attempted: float | None = None

    model_config = ConfigDict(from_attributes=True)


class CourseMasteryResponse(BaseModel):
    course_id: int
    course_title: str
    summary: CourseMasterySummary
    topics: list[TopicMasteryItemResponse]

    model_config = ConfigDict(from_attributes=True)


class TopicMasteryHistoryItemResponse(BaseModel):
    attempt_id: int
    mastery_before: float
    mastery_after: float
    answers_in_attempt: int
    correct_in_attempt: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TopicMasteryDetailResponse(TopicMasteryItemResponse):
    history: list[TopicMasteryHistoryItemResponse] = []

    model_config = ConfigDict(from_attributes=True)
