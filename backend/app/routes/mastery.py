from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.schemas.mastery import (
    CourseMasteryResponse,
    CourseMasterySummary,
    TopicMasteryDetailResponse,
    TopicMasteryHistoryItemResponse,
    TopicMasteryItemResponse,
)
from app.services.bkt import classify
from app.utils.dependencies import get_current_user

router = APIRouter(
    prefix="/api/mastery",
    tags=["Mastery"]
)


@router.get("/me", response_model=list[TopicMasteryItemResponse])
def get_my_mastery(
    course_id: int | None = Query(None, description="Optional filter by course ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves mastery status for every topic across all courses for the current user.

    Uses a single joined query to prevent N+1 overhead. Topics with no mastery row appear
    as 'not_attempted' with mastery_probability null and counts 0.
    """
    query = (
        db.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Topic.id.label("topic_id"),
            Topic.title.label("topic_title"),
            Topic.order.label("order"),
            TopicMastery.mastery_probability,
            TopicMastery.total_answers,
            TopicMastery.correct_answers,
            TopicMastery.last_answered_at,
        )
        .join(Topic, Topic.course_id == Course.id)
        .outerjoin(
            TopicMastery,
            (TopicMastery.topic_id == Topic.id) & (TopicMastery.user_id == current_user.id)
        )
    )

    if course_id is not None:
        query = query.filter(Course.id == course_id)

    rows = query.order_by(Course.id.asc(), Topic.order.asc(), Topic.id.asc()).all()

    results: list[TopicMasteryItemResponse] = []
    for row in rows:
        total_answers = row.total_answers or 0
        correct_answers = row.correct_answers or 0
        mastery_p = row.mastery_probability if total_answers > 0 else None
        status = classify(row.mastery_probability or 0.0, total_answers)

        results.append(
            TopicMasteryItemResponse(
                course_id=row.course_id,
                course_title=row.course_title,
                topic_id=row.topic_id,
                topic_title=row.topic_title,
                order=row.order,
                mastery_probability=mastery_p,
                status=status,
                total_answers=total_answers,
                correct_answers=correct_answers,
                last_answered_at=row.last_answered_at,
            )
        )

    return results


@router.get("/me/courses/{course_id}", response_model=CourseMasteryResponse)
def get_my_course_mastery(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves course summary and topic mastery breakdown for a single course.

    Uses a single joined query to verify course existence and load all topic masteries,
    preventing N+1 queries. Raises 404 if the course does not exist.
    """
    rows = (
        db.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Topic.id.label("topic_id"),
            Topic.title.label("topic_title"),
            Topic.order.label("order"),
            TopicMastery.mastery_probability,
            TopicMastery.total_answers,
            TopicMastery.correct_answers,
            TopicMastery.last_answered_at,
        )
        .outerjoin(Topic, Topic.course_id == Course.id)
        .outerjoin(
            TopicMastery,
            (TopicMastery.topic_id == Topic.id) & (TopicMastery.user_id == current_user.id)
        )
        .filter(Course.id == course_id)
        .order_by(Topic.order.asc(), Topic.id.asc())
        .all()
    )

    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")

    course_id_val = rows[0].course_id
    course_title_val = rows[0].course_title

    counts = {
        "not_attempted": 0,
        "weak": 0,
        "developing": 0,
        "strong": 0,
    }
    attempted_masteries: list[float] = []
    topic_items: list[TopicMasteryItemResponse] = []

    for row in rows:
        if row.topic_id is None:
            continue

        total_answers = row.total_answers or 0
        correct_answers = row.correct_answers or 0
        mastery_p = row.mastery_probability if total_answers > 0 else None
        status = classify(row.mastery_probability or 0.0, total_answers)

        counts[status] = counts.get(status, 0) + 1
        if total_answers > 0 and row.mastery_probability is not None:
            attempted_masteries.append(float(row.mastery_probability))

        topic_items.append(
            TopicMasteryItemResponse(
                course_id=course_id_val,
                course_title=course_title_val,
                topic_id=row.topic_id,
                topic_title=row.topic_title,
                order=row.order,
                mastery_probability=mastery_p,
                status=status,
                total_answers=total_answers,
                correct_answers=correct_answers,
                last_answered_at=row.last_answered_at,
            )
        )

    avg_mastery = (
        round(sum(attempted_masteries) / len(attempted_masteries), 4)
        if attempted_masteries
        else None
    )

    summary = CourseMasterySummary(
        total_topics=len(topic_items),
        not_attempted=counts["not_attempted"],
        weak=counts["weak"],
        developing=counts["developing"],
        strong=counts["strong"],
        average_mastery_attempted=avg_mastery,
    )

    return CourseMasteryResponse(
        course_id=course_id_val,
        course_title=course_title_val,
        summary=summary,
        topics=topic_items,
    )


@router.get("/me/topics/{topic_id}", response_model=TopicMasteryDetailResponse)
def get_my_topic_mastery(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieves mastery state and chronological progression history for a single topic.

    Raises 404 if the topic does not exist. History entries are ordered oldest first.
    """
    topic_row = (
        db.query(
            Topic.id.label("topic_id"),
            Topic.title.label("topic_title"),
            Topic.order.label("order"),
            Topic.course_id.label("course_id"),
            Course.title.label("course_title"),
            TopicMastery.mastery_probability,
            TopicMastery.total_answers,
            TopicMastery.correct_answers,
            TopicMastery.last_answered_at,
        )
        .join(Course, Course.id == Topic.course_id)
        .outerjoin(
            TopicMastery,
            (TopicMastery.topic_id == Topic.id) & (TopicMastery.user_id == current_user.id)
        )
        .filter(Topic.id == topic_id)
        .first()
    )

    if not topic_row:
        raise HTTPException(status_code=404, detail="Topic not found")

    history_rows = (
        db.query(TopicMasteryHistory)
        .filter(
            TopicMasteryHistory.user_id == current_user.id,
            TopicMasteryHistory.topic_id == topic_id,
        )
        .order_by(TopicMasteryHistory.created_at.asc(), TopicMasteryHistory.id.asc())
        .all()
    )

    total_answers = topic_row.total_answers or 0
    correct_answers = topic_row.correct_answers or 0
    mastery_p = topic_row.mastery_probability if total_answers > 0 else None
    status = classify(topic_row.mastery_probability or 0.0, total_answers)

    history_items = [
        TopicMasteryHistoryItemResponse(
            attempt_id=h.attempt_id,
            mastery_before=h.mastery_before,
            mastery_after=h.mastery_after,
            answers_in_attempt=h.answers_in_attempt,
            correct_in_attempt=h.correct_in_attempt,
            created_at=h.created_at,
        )
        for h in history_rows
    ]

    return TopicMasteryDetailResponse(
        course_id=topic_row.course_id,
        course_title=topic_row.course_title,
        topic_id=topic_row.topic_id,
        topic_title=topic_row.topic_title,
        order=topic_row.order,
        mastery_probability=mastery_p,
        status=status,
        total_answers=total_answers,
        correct_answers=correct_answers,
        last_answered_at=topic_row.last_answered_at,
        history=history_items,
    )
