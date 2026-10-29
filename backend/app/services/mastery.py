"""Mastery service handling BKT knowledge updates and database persistence.

Follows docs/KNOWLEDGE_MODEL.md Sections 5, 6, and 7.
Manages transactional row locking (SELECT ... FOR UPDATE), historical ledger recording,
and query helpers.
"""

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import bkt as bkt_config
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.services.bkt import update_mastery


def apply_attempt(
    db: Session,
    user_id: int,
    attempt: QuizAttempt,
    responses_in_order: Sequence[QuizResponse],
    as_of: datetime | None = None
) -> None:
    """Updates topic mastery and records history for all topics in a quiz attempt.

    Transactional contract:
        - Must be called inside the caller's active database transaction.
        - Uses pessimistic row locking (SELECT ... FOR UPDATE) on topic_mastery.
        - Executes db.flush() only, NEVER db.commit().
        - Idempotent: Skips processing for any (attempt_id, topic_id) already in history.

    Args:
        db: Active SQLAlchemy database session.
        user_id: ID of the learner submitting the attempt.
        attempt: The QuizAttempt instance being processed.
        responses_in_order: Sequence of QuizResponse rows in submission order.
        as_of: Optional effective timestamp (defaults to current UTC time if None).
    """
    if not responses_in_order:
        return

    # 1. Group responses by topic while strictly preserving submission order
    responses_by_topic: dict[int, list[QuizResponse]] = {}
    for resp in responses_in_order:
        responses_by_topic.setdefault(resp.topic_id, []).append(resp)

    # 2. Check for already recorded history rows for this attempt (Idempotency)
    existing_histories = (
        db.query(TopicMasteryHistory.topic_id)
        .filter(TopicMasteryHistory.attempt_id == attempt.id)
        .all()
    )
    already_processed_topics = {h[0] for h in existing_histories}

    # 3. Ensure question metadata (difficulty) is accessible
    question_ids = [r.question_id for r in responses_in_order]
    questions_cache: dict[int, Question] = {}
    if question_ids:
        loaded_questions = (
            db.query(Question)
            .filter(Question.id.in_(question_ids))
            .all()
        )
        questions_cache = {q.id: q for q in loaded_questions}

    now = datetime.now(timezone.utc)
    effective_time = as_of if as_of is not None else now

    # 4. Process each topic touched by this attempt
    for topic_id, topic_responses in responses_by_topic.items():
        if topic_id in already_processed_topics:
            continue

        mastery = get_or_create_topic_mastery(db, user_id, topic_id)

        mastery_before = float(mastery.mastery_probability)
        current_p = mastery_before
        correct_in_attempt = 0
        answers_in_attempt = len(topic_responses)

        # Apply each answer sequentially in submitted order
        for resp in topic_responses:
            if resp.is_correct:
                correct_in_attempt += 1

            q = getattr(resp, "question", None) or questions_cache.get(resp.question_id)
            difficulty = q.difficulty if q else None

            current_p = update_mastery(current_p, resp.is_correct, difficulty)

        mastery_after = current_p

        # Update point-in-time TopicMastery record
        mastery.mastery_probability = mastery_after
        mastery.total_answers += answers_in_attempt
        mastery.correct_answers += correct_in_attempt
        mastery.last_answered_at = effective_time
        mastery.updated_at = now

        # Insert immutable TopicMasteryHistory record
        history = TopicMasteryHistory(
            user_id=user_id,
            topic_id=topic_id,
            attempt_id=attempt.id,
            mastery_before=mastery_before,
            mastery_after=mastery_after,
            answers_in_attempt=answers_in_attempt,
            correct_in_attempt=correct_in_attempt,
            created_at=effective_time,
        )
        db.add(history)

    db.flush()


def get_user_mastery_rows(
    db: Session,
    user_id: int,
    course_id: int | None = None
) -> list[TopicMastery]:
    """Retrieves TopicMastery records for a user, optionally filtered by course."""
    query = db.query(TopicMastery).filter(TopicMastery.user_id == user_id)
    if course_id is not None:
        query = query.join(Topic, TopicMastery.topic_id == Topic.id).filter(Topic.course_id == course_id)
    return query.all()


def get_user_mastery_for_topic(
    db: Session,
    user_id: int,
    topic_id: int
) -> TopicMastery | None:
    """Retrieves a single TopicMastery row for a given user and topic."""
    return (
        db.query(TopicMastery)
        .filter(
            TopicMastery.user_id == user_id,
            TopicMastery.topic_id == topic_id
        )
        .first()
    )


def get_topic_mastery_history(
    db: Session,
    user_id: int,
    topic_id: int
) -> list[TopicMasteryHistory]:
    """Retrieves historical mastery progression records for a user and topic (oldest first)."""
    return (
        db.query(TopicMasteryHistory)
        .filter(
            TopicMasteryHistory.user_id == user_id,
            TopicMasteryHistory.topic_id == topic_id
        )
        .order_by(TopicMasteryHistory.created_at.asc(), TopicMasteryHistory.id.asc())
        .all()
    )


def get_or_create_topic_mastery(
    db: Session,
    user_id: int,
    topic_id: int
) -> TopicMastery:
    """Retrieves existing TopicMastery locked with FOR UPDATE, or creates it safely with savepoint.

    Handles concurrent first-submission race conditions where two simultaneous transactions
    attempt to insert the initial row.
    """
    mastery = (
        db.query(TopicMastery)
        .filter(
            TopicMastery.user_id == user_id,
            TopicMastery.topic_id == topic_id
        )
        .with_for_update()
        .first()
    )

    if not mastery:
        try:
            with db.begin_nested():
                mastery = TopicMastery(
                    user_id=user_id,
                    topic_id=topic_id,
                    mastery_probability=bkt_config.P_INIT,
                    total_answers=0,
                    correct_answers=0,
                    last_answered_at=None,
                )
                db.add(mastery)
                db.flush()
        except IntegrityError:
            # Concurrent insert won the race; re-select existing row with FOR UPDATE
            mastery = (
                db.query(TopicMastery)
                .filter(
                    TopicMastery.user_id == user_id,
                    TopicMastery.topic_id == topic_id
                )
                .with_for_update()
                .one()
            )

    return mastery

