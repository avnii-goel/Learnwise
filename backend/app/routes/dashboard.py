"""Dashboard router for LearnWise.

Provides analytics endpoints for learner and instructor dashboards.
Reference: docs/DASHBOARDS.md Section 6.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.dashboard import (
    InstructorLearnersResponse,
    InstructorOverviewResponse,
    InstructorTopicsResponse,
    LearnerDashboardResponse,
    LearnerTrendsResponse,
    QuizHistoryResponse,
)
from app.services.dashboard import (
    get_learner_dashboard_overview,
    get_learner_quiz_history,
    get_learner_trends,
)
from app.services.dashboard_instructor import (
    get_instructor_learners,
    get_instructor_overview,
    get_instructor_topics,
)
from app.utils.dependencies import get_current_user, require_instructor

router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"]
)


@router.get("/me", response_model=LearnerDashboardResponse)
def get_learner_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves comprehensive learner dashboard metrics for the authenticated user."""
    return get_learner_dashboard_overview(db, current_user.id)


@router.get("/me/history", response_model=QuizHistoryResponse)
def get_learner_history(
    limit: int = Query(20, ge=1, le=100, description="Max number of quiz attempts to return (1..100)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves paginated completed quiz attempt history for the authenticated user."""
    return get_learner_quiz_history(db, current_user.id, limit=limit)


@router.get("/me/trends", response_model=LearnerTrendsResponse)
def get_learner_trends_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves chronological quiz score and mastery progression trends for the authenticated user."""
    return get_learner_trends(db, current_user.id)


# --- Instructor Dashboard Endpoints ---

@router.get("/instructor/overview", response_model=InstructorOverviewResponse)
def get_instructor_overview_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_instructor),
):
    """Retrieves cohort-wide overview metrics across all courses and learners."""
    return get_instructor_overview(db)


@router.get("/instructor/learners", response_model=InstructorLearnersResponse)
def get_instructor_learners_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_instructor),
):
    """Retrieves performance metrics table for all learner-role accounts."""
    return get_instructor_learners(db)


@router.get("/instructor/topics", response_model=InstructorTopicsResponse)
def get_instructor_topics_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_instructor),
):
    """Retrieves competency distribution across all topics and struggle ranking."""
    return get_instructor_topics(db)


