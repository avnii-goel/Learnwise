"""Pydantic v2 schemas for LearnWise analytics dashboards.

Reference: docs/DASHBOARDS.md Section 6.
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# --- Learner Dashboard Schemas ---

class StatusCounts(BaseModel):
    strong: int = 0
    developing: int = 0
    weak: int = 0
    not_attempted: int = 0


class LearnerOverview(BaseModel):
    total_topics: int
    attempted_topics: int
    progress_percent: float
    avg_mastery_attempted: float | None = None
    status_counts: StatusCounts
    completed_quizzes: int


class TopicProgressItem(BaseModel):
    topic_id: int
    topic_title: str
    order: int
    mastery_probability: float | None = None
    status: str
    attempted: bool


class CourseProgressItem(BaseModel):
    course_id: int
    course_title: str
    total_topics: int
    attempted_topics: int
    progress_percent: float
    avg_mastery_attempted: float | None = None
    topics: list[TopicProgressItem] = Field(default_factory=list)


class TopicHighlightItem(BaseModel):
    topic_id: int
    topic_title: str
    course_title: str
    mastery_probability: float


class CurrentPathItem(BaseModel):
    rank: int
    topic_id: int
    topic_title: str
    course_title: str
    status: str
    mastery_probability: float | None = None


class LearnerDashboardResponse(BaseModel):
    overview: LearnerOverview
    courses: list[CourseProgressItem]
    strengths: list[TopicHighlightItem]
    weaknesses: list[TopicHighlightItem]
    current_path: list[CurrentPathItem]


class QuizHistoryItem(BaseModel):
    attempt_id: int
    mode: str
    course_title: str
    topic_title: str | None = None
    score: int
    total_questions: int
    percentage: float | None = None
    completed_at: datetime


class QuizHistoryResponse(BaseModel):
    items: list[QuizHistoryItem]


class QuizScoreTrendPoint(BaseModel):
    attempt_id: int
    date: datetime
    mode: str
    percentage: float


class MasteryProgressTrendPoint(BaseModel):
    attempt_id: int
    date: datetime
    avg_mastery: float


class LearnerTrendsResponse(BaseModel):
    quiz_scores: list[QuizScoreTrendPoint]
    mastery_progress: list[MasteryProgressTrendPoint]


# --- Instructor Dashboard Schemas ---

class InstructorStatusCounts(BaseModel):
    strong: int = 0
    developing: int = 0
    weak: int = 0


class InstructorCourseOverview(BaseModel):
    course_id: int
    course_title: str
    active_learners: int
    completed_attempts: int
    avg_quiz_percentage: float | None = None


class InstructorOverviewResponse(BaseModel):
    total_learners: int
    active_learners: int
    completed_attempts: int
    avg_quiz_percentage: float | None = None
    avg_mastery_attempted: float | None = None
    courses: list[InstructorCourseOverview] = Field(default_factory=list)


class InstructorLearnerItem(BaseModel):
    user_id: int
    name: str
    email: str
    attempted_topics: int
    avg_mastery_attempted: float | None = None
    completed_attempts: int
    avg_quiz_percentage: float | None = None
    last_active: datetime | None = None


class InstructorLearnersResponse(BaseModel):
    total_topics: int
    items: list[InstructorLearnerItem] = Field(default_factory=list)


class InstructorTopicItem(BaseModel):
    topic_id: int
    topic_title: str
    course_id: int
    course_title: str
    learners_attempted: int
    avg_mastery: float | None = None
    accuracy_percent: float | None = None
    weak_share_percent: float | None = None
    status_counts: InstructorStatusCounts


class InstructorTopicsResponse(BaseModel):
    min_learners_for_difficult: int
    topics: list[InstructorTopicItem] = Field(default_factory=list)
    difficult_topics: list[InstructorTopicItem] = Field(default_factory=list)


