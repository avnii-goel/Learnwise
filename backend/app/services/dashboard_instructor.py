"""Instructor analytics dashboard service module.

Provides cohort-wide overview metrics, learner cohort performance table,
topic competency distribution, and struggle/difficult topics ranking.
Reference: docs/DASHBOARDS.md Sections 4 & 6.
"""

from collections import OrderedDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.quiz_attempt import QuizAttempt
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.user import User
from app.schemas.dashboard import (
    InstructorCourseOverview,
    InstructorLearnerItem,
    InstructorLearnersResponse,
    InstructorOverviewResponse,
    InstructorStatusCounts,
    InstructorTopicItem,
    InstructorTopicsResponse,
)
from app.services.bkt import classify

MIN_LEARNERS_FOR_DIFFICULT = 5


def get_instructor_overview(db: Session) -> InstructorOverviewResponse:
    """Computes high-level cohort metrics across all learners and courses.

    Uses separate aggregate queries merged in Python to avoid row fan-out.
    """
    # 1. Total learners count
    total_learners = (
        db.query(func.count(User.id))
        .filter(User.role == "learner")
        .scalar()
        or 0
    )

    # 2. Completed attempts aggregate (active learners, completed attempts, avg quiz percentage)
    attempt_stats = (
        db.query(
            func.count(func.distinct(QuizAttempt.user_id)).label("active_learners"),
            func.count(QuizAttempt.id).label("completed_attempts"),
            func.avg(QuizAttempt.score * 100.0 / func.nullif(QuizAttempt.total_questions, 0)).label("avg_quiz_percentage"),
        )
        .join(User, User.id == QuizAttempt.user_id)
        .filter(
            User.role == "learner",
            QuizAttempt.status == "completed",
        )
        .one()
    )

    active_learners = attempt_stats.active_learners or 0
    completed_attempts = attempt_stats.completed_attempts or 0
    raw_quiz_p = attempt_stats.avg_quiz_percentage
    avg_quiz_percentage = round(float(raw_quiz_p), 1) if raw_quiz_p is not None else None

    # 3. Mean mastery probability across all attempted learner-topic rows
    raw_avg_m = (
        db.query(func.avg(TopicMastery.mastery_probability))
        .join(User, User.id == TopicMastery.user_id)
        .filter(
            User.role == "learner",
            TopicMastery.total_answers > 0,
        )
        .scalar()
    )
    avg_mastery_attempted = round(float(raw_avg_m), 4) if raw_avg_m is not None else None

    # 4. Course breakdown (all courses, even with 0 attempts)
    courses = db.query(Course.id, Course.title).order_by(Course.id.asc()).all()

    course_stats = (
        db.query(
            QuizAttempt.course_id,
            func.count(func.distinct(QuizAttempt.user_id)).label("active_learners"),
            func.count(QuizAttempt.id).label("completed_attempts"),
            func.avg(QuizAttempt.score * 100.0 / func.nullif(QuizAttempt.total_questions, 0)).label("avg_quiz_percentage"),
        )
        .join(User, User.id == QuizAttempt.user_id)
        .filter(
            User.role == "learner",
            QuizAttempt.status == "completed",
        )
        .group_by(QuizAttempt.course_id)
        .all()
    )

    stats_by_course = {
        r.course_id: {
            "active_learners": r.active_learners,
            "completed_attempts": r.completed_attempts,
            "avg_quiz_percentage": float(r.avg_quiz_percentage) if r.avg_quiz_percentage is not None else None,
        }
        for r in course_stats
    }

    course_items: list[InstructorCourseOverview] = []
    for c in courses:
        cs = stats_by_course.get(c.id, {})
        c_quiz_p = cs.get("avg_quiz_percentage")
        course_items.append(
            InstructorCourseOverview(
                course_id=c.id,
                course_title=c.title,
                active_learners=cs.get("active_learners", 0),
                completed_attempts=cs.get("completed_attempts", 0),
                avg_quiz_percentage=round(c_quiz_p, 1) if c_quiz_p is not None else None,
            )
        )

    return InstructorOverviewResponse(
        total_learners=total_learners,
        active_learners=active_learners,
        completed_attempts=completed_attempts,
        avg_quiz_percentage=avg_quiz_percentage,
        avg_mastery_attempted=avg_mastery_attempted,
        courses=course_items,
    )


def get_instructor_learners(db: Session) -> InstructorLearnersResponse:
    """Retrieves learner cohort performance table records.

    Uses separate aggregate queries merged in Python to avoid row fan-out.
    """
    total_topics = db.query(func.count(Topic.id)).scalar() or 0

    # Q1: All learner users ordered by id ASC
    learners = (
        db.query(User.id, User.name, User.email)
        .filter(User.role == "learner")
        .order_by(User.id.asc())
        .all()
    )

    # Q2: Mastery aggregate per learner (total_answers > 0)
    mastery_rows = (
        db.query(
            TopicMastery.user_id,
            func.count(TopicMastery.id).label("attempted_topics"),
            func.avg(TopicMastery.mastery_probability).label("avg_mastery"),
        )
        .join(User, User.id == TopicMastery.user_id)
        .filter(
            User.role == "learner",
            TopicMastery.total_answers > 0,
        )
        .group_by(TopicMastery.user_id)
        .all()
    )

    mastery_by_user = {
        r.user_id: {
            "attempted_topics": r.attempted_topics,
            "avg_mastery": float(r.avg_mastery) if r.avg_mastery is not None else None,
        }
        for r in mastery_rows
    }

    # Q3: Attempt aggregate per learner (completed attempts only)
    effective_date = func.coalesce(QuizAttempt.completed_at, QuizAttempt.started_at)
    attempt_rows = (
        db.query(
            QuizAttempt.user_id,
            func.count(QuizAttempt.id).label("completed_attempts"),
            func.avg(QuizAttempt.score * 100.0 / func.nullif(QuizAttempt.total_questions, 0)).label("avg_quiz_percentage"),
            func.max(effective_date).label("last_active"),
        )
        .join(User, User.id == QuizAttempt.user_id)
        .filter(
            User.role == "learner",
            QuizAttempt.status == "completed",
        )
        .group_by(QuizAttempt.user_id)
        .all()
    )

    attempts_by_user = {
        r.user_id: {
            "completed_attempts": r.completed_attempts,
            "avg_quiz_percentage": float(r.avg_quiz_percentage) if r.avg_quiz_percentage is not None else None,
            "last_active": r.last_active,
        }
        for r in attempt_rows
    }

    # Merge in Python
    items: list[InstructorLearnerItem] = []
    for l in learners:
        m = mastery_by_user.get(l.id, {})
        a = attempts_by_user.get(l.id, {})

        raw_avg_m = m.get("avg_mastery")
        avg_m = round(raw_avg_m, 4) if raw_avg_m is not None else None

        raw_avg_p = a.get("avg_quiz_percentage")
        avg_p = round(raw_avg_p, 1) if raw_avg_p is not None else None

        items.append(
            InstructorLearnerItem(
                user_id=l.id,
                name=l.name,
                email=l.email,
                attempted_topics=m.get("attempted_topics", 0),
                avg_mastery_attempted=avg_m,
                completed_attempts=a.get("completed_attempts", 0),
                avg_quiz_percentage=avg_p,
                last_active=a.get("last_active"),
            )
        )

    return InstructorLearnersResponse(
        total_topics=total_topics,
        items=items,
    )


def get_instructor_topics(db: Session) -> InstructorTopicsResponse:
    """Retrieves topic competency distribution and struggle ranking.

    Outer-joins topics with a filtered learner mastery source so topics with 0 attempts still appear.
    """
    # 1. Filtered source of learner topic mastery with total_answers > 0
    learner_mastery_subq = (
        db.query(
            TopicMastery.topic_id,
            TopicMastery.mastery_probability,
            TopicMastery.total_answers,
            TopicMastery.correct_answers,
        )
        .join(User, User.id == TopicMastery.user_id)
        .filter(
            User.role == "learner",
            TopicMastery.total_answers > 0,
        )
        .subquery("learner_mastery")
    )

    # 2. Outer join topics JOIN courses LEFT OUTER JOIN learner_mastery_subq
    rows = (
        db.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Topic.id.label("topic_id"),
            Topic.title.label("topic_title"),
            Topic.order.label("topic_order"),
            learner_mastery_subq.c.mastery_probability,
            learner_mastery_subq.c.total_answers,
            learner_mastery_subq.c.correct_answers,
        )
        .select_from(Topic)
        .join(Course, Course.id == Topic.course_id)
        .outerjoin(learner_mastery_subq, learner_mastery_subq.c.topic_id == Topic.id)
        .order_by(Course.id.asc(), Topic.order.asc(), Topic.id.asc())
        .all()
    )

    # Group rows by topic_id preserving order
    topic_groups: dict[int, dict] = OrderedDict()
    for r in rows:
        t_id = r.topic_id
        if t_id not in topic_groups:
            topic_groups[t_id] = {
                "topic_id": t_id,
                "topic_title": r.topic_title,
                "course_id": r.course_id,
                "course_title": r.course_title,
                "learner_rows": [],
            }
        if r.total_answers is not None and r.total_answers > 0:
            topic_groups[t_id]["learner_rows"].append(r)

    # Process metrics in Python
    all_topic_items: list[InstructorTopicItem] = []
    for t_id, g in topic_groups.items():
        l_rows = g["learner_rows"]
        learners_attempted = len(l_rows)

        if learners_attempted == 0:
            avg_mastery = None
            accuracy_percent = None
            weak_share_percent = None
            status_counts = {"strong": 0, "developing": 0, "weak": 0}
        else:
            # avg_mastery: arithmetic mean of mastery_probability
            sum_m = sum(r.mastery_probability for r in l_rows)
            avg_mastery = round(sum_m / learners_attempted, 4)

            # accuracy_percent: sum(correct_answers) / sum(total_answers) * 100
            sum_correct = sum(r.correct_answers or 0 for r in l_rows)
            sum_total = sum(r.total_answers or 0 for r in l_rows)
            accuracy_percent = (
                round((sum_correct / sum_total) * 100.0, 1)
                if sum_total > 0
                else None
            )

            # status_counts and weak_share_percent
            s_counts = {"strong": 0, "developing": 0, "weak": 0}
            weak_count = 0
            for r in l_rows:
                st = classify(r.mastery_probability, r.total_answers)
                if st in s_counts:
                    s_counts[st] += 1
                if st == "weak":
                    weak_count += 1

            weak_share_percent = round((weak_count / learners_attempted) * 100.0, 1)
            status_counts = s_counts

        all_topic_items.append(
            InstructorTopicItem(
                topic_id=t_id,
                topic_title=g["topic_title"],
                course_id=g["course_id"],
                course_title=g["course_title"],
                learners_attempted=learners_attempted,
                avg_mastery=avg_mastery,
                accuracy_percent=accuracy_percent,
                weak_share_percent=weak_share_percent,
                status_counts=InstructorStatusCounts(**status_counts),
            )
        )

    # Difficult topics: learners_attempted >= MIN_LEARNERS_FOR_DIFFICULT, sorted by avg_mastery ASC then topic_id ASC, top 5
    qualifying_topics = [
        t for t in all_topic_items
        if t.learners_attempted >= MIN_LEARNERS_FOR_DIFFICULT and t.avg_mastery is not None
    ]
    qualifying_topics.sort(key=lambda t: (t.avg_mastery, t.topic_id))
    difficult_topics = qualifying_topics[:5]

    return InstructorTopicsResponse(
        min_learners_for_difficult=MIN_LEARNERS_FOR_DIFFICULT,
        topics=all_topic_items,
        difficult_topics=difficult_topics,
    )

