"""Learner analytics dashboard service module.

Computes overview, course progress, strengths/weaknesses, current path recommendations,
quiz attempt history, and chronological performance trends.
Reference: docs/DASHBOARDS.md Sections 4 & 6.
"""

from collections import defaultdict
from itertools import groupby
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.quiz_attempt import QuizAttempt
from app.models.recommendation_impression import RecommendationImpression
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.schemas.dashboard import (
    CourseProgressItem,
    CurrentPathItem,
    LearnerDashboardResponse,
    LearnerOverview,
    LearnerTrendsResponse,
    MasteryProgressTrendPoint,
    QuizHistoryItem,
    QuizHistoryResponse,
    QuizScoreTrendPoint,
    StatusCounts,
    TopicHighlightItem,
    TopicProgressItem,
)
from app.services.bkt import classify


def get_learner_dashboard_overview(db: Session, user_id: int) -> LearnerDashboardResponse:
    """Computes full learner overview metrics, course breakdown, radar, strengths, and weaknesses.

    Uses a single outer-joined query for all courses/topics with the user condition in the ON clause.
    """
    # 1. Main query: all topics joined with courses and user's topic mastery
    rows = (
        db.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Topic.id.label("topic_id"),
            Topic.title.label("topic_title"),
            Topic.order.label("topic_order"),
            TopicMastery.mastery_probability,
            TopicMastery.total_answers,
        )
        .select_from(Topic)
        .join(Course, Course.id == Topic.course_id)
        .outerjoin(
            TopicMastery,
            and_(
                TopicMastery.topic_id == Topic.id,
                TopicMastery.user_id == user_id,
            ),
        )
        .order_by(Course.id.asc(), Topic.order.asc(), Topic.id.asc())
        .all()
    )

    total_topics_count = len(rows)
    attempted_topics_count = 0
    attempted_mastery_sum = 0.0

    status_counts_dict = {
        "strong": 0,
        "developing": 0,
        "weak": 0,
        "not_attempted": 0,
    }

    # Data structures for courses and topic lookup
    courses_dict: dict[int, dict] = {}
    candidate_strengths: list[dict] = []
    candidate_weaknesses: list[dict] = []
    topic_lookup: dict[int, dict] = {}

    for r in rows:
        c_id = r.course_id
        c_title = r.course_title
        t_id = r.topic_id
        t_title = r.topic_title
        t_order = r.topic_order
        m_prob = r.mastery_probability
        t_answers = r.total_answers or 0

        attempted = bool(r.total_answers is not None and r.total_answers > 0)
        status = classify(m_prob or 0.0, t_answers)
        status_counts_dict[status] = status_counts_dict.get(status, 0) + 1

        mastery_val: float | None = None
        if attempted and m_prob is not None:
            attempted_topics_count += 1
            attempted_mastery_sum += m_prob
            mastery_val = round(m_prob, 4)

        # Cache topic info for current_path and strengths/weaknesses
        topic_lookup[t_id] = {
            "title": t_title,
            "course_title": c_title,
            "status": status,
            "mastery_probability": mastery_val,
        }

        # Initialize course bucket
        if c_id not in courses_dict:
            courses_dict[c_id] = {
                "course_id": c_id,
                "course_title": c_title,
                "total_topics": 0,
                "attempted_topics": 0,
                "attempted_mastery_sum": 0.0,
                "topics": [],
            }

        c_bucket = courses_dict[c_id]
        c_bucket["total_topics"] += 1
        if attempted and m_prob is not None:
            c_bucket["attempted_topics"] += 1
            c_bucket["attempted_mastery_sum"] += m_prob

        c_bucket["topics"].append(
            TopicProgressItem(
                topic_id=t_id,
                topic_title=t_title,
                order=t_order,
                mastery_probability=mastery_val,
                status=status,
                attempted=attempted,
            )
        )

        if status == "strong" and mastery_val is not None:
            candidate_strengths.append({
                "topic_id": t_id,
                "topic_title": t_title,
                "course_title": c_title,
                "mastery_probability": mastery_val,
            })
        elif status == "weak" and mastery_val is not None:
            candidate_weaknesses.append({
                "topic_id": t_id,
                "topic_title": t_title,
                "course_title": c_title,
                "mastery_probability": mastery_val,
            })

    # Overall metrics
    progress_percent = (
        round((attempted_topics_count / total_topics_count) * 100.0, 1)
        if total_topics_count > 0
        else 0.0
    )
    avg_mastery_attempted = (
        round(attempted_mastery_sum / attempted_topics_count, 4)
        if attempted_topics_count > 0
        else None
    )

    # 2. Completed quizzes count
    completed_quizzes = (
        db.query(func.count(QuizAttempt.id))
        .filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.status == "completed",
        )
        .scalar()
        or 0
    )

    overview = LearnerOverview(
        total_topics=total_topics_count,
        attempted_topics=attempted_topics_count,
        progress_percent=progress_percent,
        avg_mastery_attempted=avg_mastery_attempted,
        status_counts=StatusCounts(**status_counts_dict),
        completed_quizzes=completed_quizzes,
    )

    # Assemble course progress items
    course_items: list[CourseProgressItem] = []
    for c_id in sorted(courses_dict.keys()):
        cb = courses_dict[c_id]
        c_tot = cb["total_topics"]
        c_att = cb["attempted_topics"]
        c_prog = round((c_att / c_tot) * 100.0, 1) if c_tot > 0 else 0.0
        c_avg_m = (
            round(cb["attempted_mastery_sum"] / c_att, 4)
            if c_att > 0
            else None
        )
        course_items.append(
            CourseProgressItem(
                course_id=c_id,
                course_title=cb["course_title"],
                total_topics=c_tot,
                attempted_topics=c_att,
                progress_percent=c_prog,
                avg_mastery_attempted=c_avg_m,
                topics=cb["topics"],
            )
        )

    # Strengths: strong, mastery DESC, topic_id ASC, max 3
    candidate_strengths.sort(
        key=lambda x: (-x["mastery_probability"], x["topic_id"])
    )
    strengths = [TopicHighlightItem(**s) for s in candidate_strengths[:3]]

    # Weaknesses: weak, mastery ASC, topic_id ASC, max 3
    candidate_weaknesses.sort(
        key=lambda x: (x["mastery_probability"], x["topic_id"])
    )
    weaknesses = [TopicHighlightItem(**w) for w in candidate_weaknesses[:3]]

    # 3. Current Path: user's latest request_id in recommendation_impressions
    latest_req_row = (
        db.query(RecommendationImpression.request_id)
        .filter(RecommendationImpression.user_id == user_id)
        .order_by(RecommendationImpression.shown_at.desc(), RecommendationImpression.id.desc())
        .first()
    )

    current_path: list[CurrentPathItem] = []
    if latest_req_row is not None:
        latest_request_id = latest_req_row[0]
        topic_ranks = (
            db.query(
                RecommendationImpression.topic_id,
                func.min(RecommendationImpression.rank).label("min_rank"),
            )
            .filter(RecommendationImpression.request_id == latest_request_id)
            .group_by(RecommendationImpression.topic_id)
            .order_by(func.min(RecommendationImpression.rank).asc(), RecommendationImpression.topic_id.asc())
            .limit(3)
            .all()
        )

        for idx, (t_id, _) in enumerate(topic_ranks, start=1):
            t_info = topic_lookup.get(t_id)
            if t_info:
                current_path.append(
                    CurrentPathItem(
                        rank=idx,
                        topic_id=t_id,
                        topic_title=t_info["title"],
                        course_title=t_info["course_title"],
                        status=t_info["status"],
                        mastery_probability=t_info["mastery_probability"],
                    )
                )

    return LearnerDashboardResponse(
        overview=overview,
        courses=course_items,
        strengths=strengths,
        weaknesses=weaknesses,
        current_path=current_path,
    )


def get_learner_quiz_history(db: Session, user_id: int, limit: int = 20) -> QuizHistoryResponse:
    """Retrieves paginated completed quiz attempt history for the learner.

    Ordered by COALESCE(completed_at, started_at) DESC, id DESC.
    """
    effective_date = func.coalesce(QuizAttempt.completed_at, QuizAttempt.started_at)

    rows = (
        db.query(
            QuizAttempt.id.label("attempt_id"),
            QuizAttempt.mode,
            Course.title.label("course_title"),
            Topic.title.label("topic_title"),
            QuizAttempt.score,
            QuizAttempt.total_questions,
            effective_date.label("completed_at"),
        )
        .join(Course, Course.id == QuizAttempt.course_id)
        .outerjoin(Topic, Topic.id == QuizAttempt.topic_id)
        .filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.status == "completed",
        )
        .order_by(effective_date.desc(), QuizAttempt.id.desc())
        .limit(limit)
        .all()
    )

    items: list[QuizHistoryItem] = []
    for r in rows:
        percentage: float | None = None
        if r.total_questions and r.total_questions > 0:
            percentage = round((r.score / r.total_questions) * 100.0, 1)

        # topic_title is null for fixed attempts
        topic_title = r.topic_title if r.mode == "adaptive" else None

        items.append(
            QuizHistoryItem(
                attempt_id=r.attempt_id,
                mode=r.mode,
                course_title=r.course_title,
                topic_title=topic_title,
                score=r.score,
                total_questions=r.total_questions,
                percentage=percentage,
                completed_at=r.completed_at,
            )
        )

    return QuizHistoryResponse(items=items)


def get_learner_trends(db: Session, user_id: int) -> LearnerTrendsResponse:
    """Retrieves chronological quiz score history and cumulative mastery progression trend.

    Both return the last 30 data points.
    """
    effective_date = func.coalesce(QuizAttempt.completed_at, QuizAttempt.started_at)

    # 1. Quiz scores: all completed attempts ordered chronologically
    score_rows = (
        db.query(
            QuizAttempt.id.label("attempt_id"),
            effective_date.label("date"),
            QuizAttempt.mode,
            QuizAttempt.score,
            QuizAttempt.total_questions,
        )
        .filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.status == "completed",
        )
        .order_by(effective_date.asc(), QuizAttempt.id.asc())
        .all()
    )

    # Keep last 30 points
    if len(score_rows) > 30:
        score_rows = score_rows[-30:]

    quiz_scores = [
        QuizScoreTrendPoint(
            attempt_id=r.attempt_id,
            date=r.date,
            mode=r.mode,
            percentage=(
                round((r.score / r.total_questions) * 100.0, 1)
                if (r.total_questions and r.total_questions > 0)
                else 0.0
            ),
        )
        for r in score_rows
    ]

    # 2. Cumulative mastery progression: topic_mastery_history joined with completed attempts
    history_rows = (
        db.query(
            TopicMasteryHistory.attempt_id,
            TopicMasteryHistory.topic_id,
            TopicMasteryHistory.mastery_after,
            effective_date.label("date"),
        )
        .join(QuizAttempt, QuizAttempt.id == TopicMasteryHistory.attempt_id)
        .filter(
            TopicMasteryHistory.user_id == user_id,
            QuizAttempt.status == "completed",
        )
        .order_by(TopicMasteryHistory.attempt_id.asc(), TopicMasteryHistory.topic_id.asc())
        .all()
    )

    latest_topic_mastery: dict[int, float] = {}
    mastery_points: list[MasteryProgressTrendPoint] = []

    for attempt_id, group_iter in groupby(history_rows, key=lambda x: x.attempt_id):
        group_items = list(group_iter)
        attempt_date = group_items[0].date
        for it in group_items:
            latest_topic_mastery[it.topic_id] = it.mastery_after

        if latest_topic_mastery:
            mean_m = sum(latest_topic_mastery.values()) / len(latest_topic_mastery)
            mastery_points.append(
                MasteryProgressTrendPoint(
                    attempt_id=attempt_id,
                    date=attempt_date,
                    avg_mastery=round(mean_m, 4),
                )
            )

    # Cap AFTER computing all points
    if len(mastery_points) > 30:
        mastery_points = mastery_points[-30:]

    return LearnerTrendsResponse(
        quiz_scores=quiz_scores,
        mastery_progress=mastery_points,
    )

