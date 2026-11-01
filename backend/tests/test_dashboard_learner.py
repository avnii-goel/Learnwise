"""Unit and integration tests for learner dashboard analytics endpoints.

Tests:
1. test_dashboard_me_worked_example
2. test_dashboard_trends_worked_example
3. test_dashboard_new_learner_empty_state
4. test_dashboard_excludes_in_progress
5. test_dashboard_history_order_limit_and_null_completed_at
6. test_dashboard_trends_cap_30
7. test_dashboard_current_path
8. test_dashboard_no_cross_user_leakage
9. test_dashboard_requires_auth
10. test_dashboard_me_query_count

Reference: docs/DASHBOARDS.md Sections 4, 5, 6, 10.
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest
from fastapi import status
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.learningresource import LearningResource
from app.models.quiz_attempt import QuizAttempt
from app.models.recommendation_impression import RecommendationImpression
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.utils.jwt import create_access_token
from app.utils.security import hash_password


def test_dashboard_me_worked_example(client, learner_token, test_learner, db_session: Session):
    """Worked example from Section 5:

    24 topics total across 4 courses.
    Learner attempted 3 topics:
    - T1: mastery 0.85 (total 4, correct 4) -> strong
    - T2: mastery 0.646 (total 1, correct 1) -> developing
    - T3: mastery 0.1486 (total 1, correct 0) -> weak
    Remaining 21 topics: not attempted.
    Asserts exact values: progress 12.5%, avg_mastery 0.5482, status counts, strengths, weaknesses.
    """
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    assert len(topics) == 24, "Seeded baseline database must have 24 topics across 4 courses."

    t1, t2, t3 = topics[0], topics[1], topics[2]

    # Insert topic mastery records
    db_session.add_all([
        TopicMastery(
            user_id=test_learner.id,
            topic_id=t1.id,
            mastery_probability=0.85,
            total_answers=4,
            correct_answers=4,
        ),
        TopicMastery(
            user_id=test_learner.id,
            topic_id=t2.id,
            mastery_probability=0.646,
            total_answers=1,
            correct_answers=1,
        ),
        TopicMastery(
            user_id=test_learner.id,
            topic_id=t3.id,
            mastery_probability=0.1486,
            total_answers=1,
            correct_answers=0,
        ),
    ])
    db_session.commit()

    resp = client.get("/api/dashboard/me", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    overview = data["overview"]
    assert overview["total_topics"] == 24
    assert overview["attempted_topics"] == 3
    assert overview["progress_percent"] == 12.5
    assert overview["avg_mastery_attempted"] == 0.5482
    assert overview["status_counts"] == {
        "strong": 1,
        "developing": 1,
        "weak": 1,
        "not_attempted": 21,
    }
    assert overview["completed_quizzes"] == 0

    # Strengths and weaknesses
    assert len(data["strengths"]) == 1
    assert data["strengths"][0]["topic_id"] == t1.id
    assert data["strengths"][0]["mastery_probability"] == 0.85

    assert len(data["weaknesses"]) == 1
    assert data["weaknesses"][0]["topic_id"] == t3.id
    assert data["weaknesses"][0]["mastery_probability"] == 0.1486

    # Courses breakdown
    courses = data["courses"]
    assert len(courses) == 4
    total_course_topics = sum(len(c["topics"]) for c in courses)
    assert total_course_topics == 24

    for course in courses:
        for top in course["topics"]:
            if top["topic_id"] == t1.id:
                assert top["attempted"] is True
                assert top["status"] == "strong"
                assert top["mastery_probability"] == 0.85
            elif top["topic_id"] == t2.id:
                assert top["attempted"] is True
                assert top["status"] == "developing"
                assert top["mastery_probability"] == 0.646
            elif top["topic_id"] == t3.id:
                assert top["attempted"] is True
                assert top["status"] == "weak"
                assert top["mastery_probability"] == 0.1486
            else:
                assert top["attempted"] is False
                assert top["status"] == "not_attempted"
                assert top["mastery_probability"] is None


def test_dashboard_trends_worked_example(client, learner_token, test_learner, db_session: Session):
    """Worked example from Section 5:

    Attempts in chronological order T2, T3, T1 (one topic each):
    - T2: mastery_after = 0.646 -> avg = 0.646
    - T3: mastery_after = 0.1486 -> avg = (0.646 + 0.1486)/2 = 0.3973
    - T1: mastery_after = 0.85 -> avg = (0.85 + 0.646 + 0.1486)/3 = 0.5482
    Asserts mastery_progress == [0.646, 0.3973, 0.5482].
    Asserts quiz_scores has 3 points in chronological order with correct percentages.
    """
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    t1, t2, t3 = topics[0], topics[1], topics[2]

    base_time = datetime.now(timezone.utc) - timedelta(days=2)
    t_times = [
        base_time + timedelta(hours=1),
        base_time + timedelta(hours=2),
        base_time + timedelta(hours=3),
    ]

    # Create 3 attempts in order T2, T3, T1
    att1 = QuizAttempt(
        user_id=test_learner.id,
        course_id=t2.course_id,
        topic_id=t2.id,
        mode="adaptive",
        status="completed",
        score=6,
        total_questions=8,
        started_at=t_times[0],
        completed_at=t_times[0],
    )
    att2 = QuizAttempt(
        user_id=test_learner.id,
        course_id=t3.course_id,
        topic_id=t3.id,
        mode="adaptive",
        status="completed",
        score=3,
        total_questions=8,
        started_at=t_times[1],
        completed_at=t_times[1],
    )
    att3 = QuizAttempt(
        user_id=test_learner.id,
        course_id=t1.course_id,
        topic_id=t1.id,
        mode="adaptive",
        status="completed",
        score=7,
        total_questions=8,
        started_at=t_times[2],
        completed_at=t_times[2],
    )
    db_session.add_all([att1, att2, att3])
    db_session.flush()

    # TopicMasteryHistory for each attempt
    h1 = TopicMasteryHistory(
        user_id=test_learner.id,
        attempt_id=att1.id,
        topic_id=t2.id,
        mastery_before=0.30,
        mastery_after=0.6460,
        answers_in_attempt=1,
        correct_in_attempt=1,
        created_at=t_times[0],
    )
    h2 = TopicMasteryHistory(
        user_id=test_learner.id,
        attempt_id=att2.id,
        topic_id=t3.id,
        mastery_before=0.30,
        mastery_after=0.1486,
        answers_in_attempt=1,
        correct_in_attempt=0,
        created_at=t_times[1],
    )
    h3 = TopicMasteryHistory(
        user_id=test_learner.id,
        attempt_id=att3.id,
        topic_id=t1.id,
        mastery_before=0.30,
        mastery_after=0.8500,
        answers_in_attempt=1,
        correct_in_attempt=1,
        created_at=t_times[2],
    )
    db_session.add_all([h1, h2, h3])
    db_session.commit()

    resp = client.get("/api/dashboard/me/trends", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    # Verify quiz scores: 6/8 = 75.0%, 3/8 = 37.5%, 7/8 = 87.5%
    quiz_scores = data["quiz_scores"]
    assert len(quiz_scores) == 3
    assert [p["percentage"] for p in quiz_scores] == [75.0, 37.5, 87.5]
    assert [p["attempt_id"] for p in quiz_scores] == [att1.id, att2.id, att3.id]

    # Verify cumulative mastery progression: [0.646, 0.3973, 0.5482]
    mastery_prog = data["mastery_progress"]
    assert len(mastery_prog) == 3
    assert [p["avg_mastery"] for p in mastery_prog] == [0.646, 0.3973, 0.5482]
    assert [p["attempt_id"] for p in mastery_prog] == [att1.id, att2.id, att3.id]


def test_dashboard_new_learner_empty_state(client, learner_token, db_session: Session):
    """Fresh learner with zero data receives zeros, null averages, and empty lists."""
    # 1. /me
    resp_me = client.get("/api/dashboard/me", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_me.status_code == status.HTTP_200_OK
    data_me = resp_me.json()

    assert data_me["overview"]["total_topics"] == 24
    assert data_me["overview"]["attempted_topics"] == 0
    assert data_me["overview"]["progress_percent"] == 0.0
    assert data_me["overview"]["avg_mastery_attempted"] is None
    assert data_me["overview"]["status_counts"] == {
        "strong": 0,
        "developing": 0,
        "weak": 0,
        "not_attempted": 24,
    }
    assert data_me["overview"]["completed_quizzes"] == 0
    assert data_me["strengths"] == []
    assert data_me["weaknesses"] == []
    assert data_me["current_path"] == []

    # 2. /me/history
    resp_hist = client.get("/api/dashboard/me/history", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_hist.status_code == status.HTTP_200_OK
    assert resp_hist.json() == {"items": []}

    # 3. /me/trends
    resp_trends = client.get("/api/dashboard/me/trends", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_trends.status_code == status.HTTP_200_OK
    assert resp_trends.json() == {"quiz_scores": [], "mastery_progress": []}


def test_dashboard_excludes_in_progress(client, learner_token, test_learner, db_session: Session):
    """In-progress adaptive attempt is never counted in history, trends, or completed_quizzes."""
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()

    now = datetime.now(timezone.utc)
    in_prog = QuizAttempt(
        user_id=test_learner.id,
        course_id=course.id,
        topic_id=topic.id,
        mode="adaptive",
        status="in_progress",
        score=2,
        total_questions=8,
        started_at=now,
        completed_at=None,
    )
    db_session.add(in_prog)
    db_session.commit()

    # /me: completed_quizzes remains 0
    resp_me = client.get("/api/dashboard/me", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_me.status_code == status.HTTP_200_OK
    assert resp_me.json()["overview"]["completed_quizzes"] == 0

    # /history: items remains empty
    resp_hist = client.get("/api/dashboard/me/history", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_hist.status_code == status.HTTP_200_OK
    assert resp_hist.json()["items"] == []

    # /trends: quiz_scores remains empty
    resp_trends = client.get("/api/dashboard/me/trends", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_trends.status_code == status.HTTP_200_OK
    assert resp_trends.json()["quiz_scores"] == []


def test_dashboard_history_order_limit_and_null_completed_at(client, learner_token, test_learner, db_session: Session):
    """History ordering newest first, limit query clamping, null completed_at fallback to started_at, mode/topic checks."""
    courses = db_session.query(Course).all()
    c1 = courses[0]
    t1 = db_session.query(Topic).filter(Topic.course_id == c1.id).first()

    now = datetime.now(timezone.utc)
    t_early = now - timedelta(days=3)
    t_mid = now - timedelta(days=2)
    t_late = now - timedelta(days=1)

    # Attempt 1: Early, completed_at is NULL -> effective_date is t_early
    att1 = QuizAttempt(
        user_id=test_learner.id,
        course_id=c1.id,
        topic_id=t1.id,
        mode="adaptive",
        status="completed",
        score=6,
        total_questions=8,
        started_at=t_early,
        completed_at=None,
    )
    # Attempt 2: Mid, fixed quiz -> topic_title is null
    att2 = QuizAttempt(
        user_id=test_learner.id,
        course_id=c1.id,
        topic_id=None,
        mode="fixed",
        status="completed",
        score=15,
        total_questions=20,
        started_at=t_mid,
        completed_at=t_mid,
    )
    # Attempt 3: Late
    att3 = QuizAttempt(
        user_id=test_learner.id,
        course_id=c1.id,
        topic_id=t1.id,
        mode="adaptive",
        status="completed",
        score=8,
        total_questions=8,
        started_at=t_late,
        completed_at=t_late,
    )
    db_session.add_all([att1, att2, att3])
    db_session.commit()

    # Query with default limit=20
    resp = client.get("/api/dashboard/me/history", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 3

    # Ordering newest first: att3 (late), att2 (mid), att1 (early)
    assert items[0]["attempt_id"] == att3.id
    assert items[1]["attempt_id"] == att2.id
    assert items[2]["attempt_id"] == att1.id

    # Fallback to started_at when completed_at is NULL
    assert items[2]["completed_at"] is not None
    assert items[2]["percentage"] == 75.0  # 6/8 = 75.0%

    # Topic title null for fixed quiz, present for adaptive
    assert items[0]["topic_title"] == t1.title
    assert items[1]["topic_title"] is None
    assert items[1]["mode"] == "fixed"

    # Limit parameter works
    resp_limit = client.get("/api/dashboard/me/history?limit=2", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_limit.status_code == status.HTTP_200_OK
    assert len(resp_limit.json()["items"]) == 2

    # Validation: limit=0 or limit=101 returns 422
    assert client.get("/api/dashboard/me/history?limit=0", headers={"Authorization": f"Bearer {learner_token}"}).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert client.get("/api/dashboard/me/history?limit=101", headers={"Authorization": f"Bearer {learner_token}"}).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_dashboard_trends_cap_30(client, learner_token, test_learner, db_session: Session):
    """35 completed attempts -> exactly 30 points in each list, and mastery values reflect all 35 attempts."""
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    t1 = topics[0]

    base_time = datetime.now(timezone.utc) - timedelta(days=40)

    attempts = []
    histories = []
    for i in range(1, 36):
        t_time = base_time + timedelta(days=i)
        att = QuizAttempt(
            user_id=test_learner.id,
            course_id=t1.course_id,
            topic_id=t1.id,
            mode="adaptive",
            status="completed",
            score=min(8, i % 8 + 1),
            total_questions=8,
            started_at=t_time,
            completed_at=t_time,
        )
        attempts.append(att)

    db_session.add_all(attempts)
    db_session.flush()

    for idx, att in enumerate(attempts, start=1):
        # Progressively update mastery: mastery increases with attempt index
        h = TopicMasteryHistory(
            user_id=test_learner.id,
            attempt_id=att.id,
            topic_id=t1.id,
            mastery_before=0.20,
            mastery_after=round(0.20 + (idx * 0.02), 4),
            answers_in_attempt=1,
            correct_in_attempt=1,
            created_at=att.completed_at,
        )
        histories.append(h)

    db_session.add_all(histories)
    db_session.commit()

    resp = client.get("/api/dashboard/me/trends", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    quiz_scores = data["quiz_scores"]
    mastery_prog = data["mastery_progress"]

    assert len(quiz_scores) == 30
    assert len(mastery_prog) == 30

    # Ensure they are the LAST 30 attempts (attempts 6 to 35)
    last_30_att_ids = [att.id for att in attempts[-30:]]
    assert [p["attempt_id"] for p in quiz_scores] == last_30_att_ids
    assert [p["attempt_id"] for p in mastery_prog] == last_30_att_ids

    # Final mastery point should reflect attempt 35 mastery_after: 0.20 + (35 * 0.02) = 0.9000
    assert mastery_prog[-1]["avg_mastery"] == 0.9000


def test_dashboard_current_path(client, learner_token, test_learner, db_session: Session):
    """Impressions from older and newer requests: only newer is used, ordered by best rank, max 3, live status."""
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    t1, t2, t3, t4, t5, t6 = topics[:6]

    # Set up a learning resource
    resource = LearningResource(
        topic_id=t1.id,
        title="Sample Resource",
        resource_type="article",
        url="https://example.com/res",
        difficulty="medium",
        order=1,
    )
    db_session.add(resource)
    db_session.flush()

    # Set up mastery for live values
    db_session.add_all([
        TopicMastery(user_id=test_learner.id, topic_id=t1.id, mastery_probability=0.85, total_answers=4, correct_answers=4),  # strong
        TopicMastery(user_id=test_learner.id, topic_id=t2.id, mastery_probability=0.60, total_answers=2, correct_answers=1),  # developing
        TopicMastery(user_id=test_learner.id, topic_id=t3.id, mastery_probability=0.20, total_answers=1, correct_answers=0),  # weak
    ])
    db_session.commit()

    req_old = uuid.uuid4()
    req_new = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Older impressions (2 days ago)
    db_session.add(
        RecommendationImpression(
            user_id=test_learner.id,
            resource_id=resource.id,
            topic_id=t4.id,
            request_id=req_old,
            strategy="hybrid",
            rank=1,
            score=0.9,
            mastery_at_shown=0.1,
            components={"need": 1.0, "semantic": 0.5, "difficulty_fit": 0.8, "collaborative": 0.0},
            reason="Old recommendation",
            shown_at=now - timedelta(days=2),
            is_synthetic=False,
        )
    )

    # Newer impressions (1 day ago) with topics t3 (rank 1), t1 (rank 2), t2 (rank 4)
    db_session.add_all([
        RecommendationImpression(
            user_id=test_learner.id,
            resource_id=resource.id,
            topic_id=t3.id,
            request_id=req_new,
            strategy="hybrid",
            rank=1,
            score=0.95,
            mastery_at_shown=0.1,
            components={"need": 1.0, "semantic": 0.5, "difficulty_fit": 0.8, "collaborative": 0.0},
            reason="Top recommendation",
            shown_at=now - timedelta(days=1),
            is_synthetic=False,
        ),
        RecommendationImpression(
            user_id=test_learner.id,
            resource_id=resource.id,
            topic_id=t1.id,
            request_id=req_new,
            strategy="hybrid",
            rank=2,
            score=0.85,
            mastery_at_shown=0.8,
            components={"need": 0.5, "semantic": 0.5, "difficulty_fit": 0.8, "collaborative": 0.0},
            reason="Second recommendation",
            shown_at=now - timedelta(days=1),
            is_synthetic=False,
        ),
        RecommendationImpression(
            user_id=test_learner.id,
            resource_id=resource.id,
            topic_id=t2.id,
            request_id=req_new,
            strategy="hybrid",
            rank=4,
            score=0.75,
            mastery_at_shown=0.5,
            components={"need": 0.7, "semantic": 0.5, "difficulty_fit": 0.8, "collaborative": 0.0},
            reason="Third recommendation",
            shown_at=now - timedelta(days=1),
            is_synthetic=False,
        ),
    ])
    db_session.commit()

    initial_imp_count = db_session.query(RecommendationImpression).count()

    resp = client.get("/api/dashboard/me", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    current_path = data["current_path"]
    assert len(current_path) == 3

    # Sorted by lowest rank: t3 (rank 1), t1 (rank 2), t2 (rank 4)
    # Output rank is sequential position 1, 2, 3
    assert current_path[0]["topic_id"] == t3.id
    assert current_path[0]["rank"] == 1
    assert current_path[0]["status"] == "weak"  # LIVE status from TopicMastery
    assert current_path[0]["mastery_probability"] == 0.20

    assert current_path[1]["topic_id"] == t1.id
    assert current_path[1]["rank"] == 2
    assert current_path[1]["status"] == "strong"  # LIVE status
    assert current_path[1]["mastery_probability"] == 0.85

    assert current_path[2]["topic_id"] == t2.id
    assert current_path[2]["rank"] == 3
    assert current_path[2]["status"] == "developing"  # LIVE status
    assert current_path[2]["mastery_probability"] == 0.60

    # Ensure calling GET /api/dashboard/me does NOT insert any new impressions
    final_imp_count = db_session.query(RecommendationImpression).count()
    assert final_imp_count == initial_imp_count


def test_dashboard_no_cross_user_leakage(client, learner_token, test_learner, db_session: Session):
    """Another user's mastery/attempts/impressions never appear in this user's dashboard."""
    other_user = User(
        name="Other Learner",
        email="other.learner@example.com",
        password_hash=hash_password("OtherPass123!"),
        role="learner",
    )
    db_session.add(other_user)
    db_session.flush()

    topics = db_session.query(Topic).all()
    t1 = topics[0]

    # Give other_user high mastery and completed quizzes
    now = datetime.now(timezone.utc)
    db_session.add_all([
        TopicMastery(user_id=other_user.id, topic_id=t1.id, mastery_probability=0.99, total_answers=10, correct_answers=10),
        QuizAttempt(user_id=other_user.id, course_id=t1.course_id, topic_id=t1.id, mode="adaptive", status="completed", score=8, total_questions=8, started_at=now, completed_at=now),
    ])
    db_session.commit()

    # Query with test_learner's token
    resp_me = client.get("/api/dashboard/me", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_me.status_code == status.HTTP_200_OK
    data = resp_me.json()

    assert data["overview"]["attempted_topics"] == 0
    assert data["overview"]["completed_quizzes"] == 0
    assert data["strengths"] == []

    resp_hist = client.get("/api/dashboard/me/history", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_hist.json()["items"] == []

    resp_trends = client.get("/api/dashboard/me/trends", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp_trends.json()["quiz_scores"] == []


def test_dashboard_requires_auth(client):
    """All 3 learner dashboard endpoints return 401 Unauthorized without token."""
    assert client.get("/api/dashboard/me").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/api/dashboard/me/history").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/api/dashboard/me/trends").status_code == status.HTTP_401_UNAUTHORIZED


def test_dashboard_me_query_count(client, learner_token, test_learner, db_session: Session):
    """Count SQL queries for all three learner endpoints; must be <= 8 total for /me."""
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    t1, t2, t3 = topics[:3]

    now = datetime.now(timezone.utc)
    att = QuizAttempt(
        user_id=test_learner.id,
        course_id=t1.course_id,
        topic_id=t1.id,
        mode="adaptive",
        status="completed",
        score=6,
        total_questions=8,
        started_at=now,
        completed_at=now,
    )
    db_session.add(att)
    db_session.flush()

    db_session.add_all([
        TopicMastery(user_id=test_learner.id, topic_id=t1.id, mastery_probability=0.85, total_answers=4, correct_answers=4),
        TopicMastery(user_id=test_learner.id, topic_id=t2.id, mastery_probability=0.646, total_answers=1, correct_answers=1),
        TopicMastery(user_id=test_learner.id, topic_id=t3.id, mastery_probability=0.1486, total_answers=1, correct_answers=0),
        TopicMasteryHistory(user_id=test_learner.id, attempt_id=att.id, topic_id=t1.id, mastery_before=0.3, mastery_after=0.85, answers_in_attempt=1, correct_in_attempt=1, created_at=now),
    ])
    db_session.commit()

    from tests.conftest import test_engine

    headers = {"Authorization": f"Bearer {learner_token}"}

    # 1. /api/dashboard/me
    query_count_me = 0
    def count_me(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count_me
        query_count_me += 1

    event.listen(test_engine, "before_cursor_execute", count_me)
    try:
        resp_me = client.get("/api/dashboard/me", headers=headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", count_me)

    assert resp_me.status_code == status.HTTP_200_OK
    assert query_count_me <= 8, f"Expected <= 8 queries for /me, got {query_count_me}"

    # 2. /api/dashboard/me/history
    query_count_hist = 0
    def count_hist(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count_hist
        query_count_hist += 1

    event.listen(test_engine, "before_cursor_execute", count_hist)
    try:
        resp_hist = client.get("/api/dashboard/me/history", headers=headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", count_hist)

    assert resp_hist.status_code == status.HTTP_200_OK

    # 3. /api/dashboard/me/trends
    query_count_trends = 0
    def count_trends(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count_trends
        query_count_trends += 1

    event.listen(test_engine, "before_cursor_execute", count_trends)
    try:
        resp_trends = client.get("/api/dashboard/me/trends", headers=headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", count_trends)

    assert resp_trends.status_code == status.HTTP_200_OK

    print(f"\n[QUERY COUNTS] /api/dashboard/me: {query_count_me} SQL queries | /api/dashboard/me/history: {query_count_hist} SQL queries | /api/dashboard/me/trends: {query_count_trends} SQL queries")
