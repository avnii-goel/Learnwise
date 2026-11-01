"""Unit and integration tests for instructor analytics dashboard endpoints.

Tests:
1. test_instructor_topics_worked_example
2. test_instructor_difficult_topics_rules
3. test_instructor_quiz_average_is_mean_of_attempt_percentages
4. test_instructor_learners_no_fanout
5. test_instructor_excludes_in_progress_and_instructor_data
6. test_instructor_empty_platform
7. test_instructor_authorization
8. test_instructor_query_count_independent_of_learner_count

Reference: docs/DASHBOARDS.md Sections 4, 5, 6, 10.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi import status
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.quiz_attempt import QuizAttempt
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.user import User
from app.services.dashboard_instructor import MIN_LEARNERS_FOR_DIFFICULT
from app.utils.security import hash_password


def test_instructor_topics_worked_example(client, instructor_token, db_session: Session):
    """Worked example from Section 5:

    Three learners on one topic:
    - Learner 1: mastery 0.85 (4 answers, 4 correct) -> strong
    - Learner 2: mastery 0.646 (1 answer, 1 correct) -> developing
    - Learner 3: mastery 0.1486 (1 answer, 0 correct) -> weak
    Asserts:
    - avg_mastery == 0.5482
    - accuracy_percent == 83.3
    - weak_share_percent == 33.3
    - status_counts == {"strong": 1, "developing": 1, "weak": 1}
    - learners_attempted == 3
    - Topic is NOT in difficult_topics (3 < MIN_LEARNERS_FOR_DIFFICULT = 5).
    """
    topic = db_session.query(Topic).order_by(Topic.id.asc()).first()
    assert topic is not None

    learners = []
    for i in range(1, 4):
        u = User(
            name=f"Learner {i}",
            email=f"learner{i}@example.com",
            password_hash=hash_password("Pass123!"),
            role="learner",
        )
        learners.append(u)
    db_session.add_all(learners)
    db_session.flush()

    db_session.add_all([
        TopicMastery(user_id=learners[0].id, topic_id=topic.id, mastery_probability=0.8500, total_answers=4, correct_answers=4),
        TopicMastery(user_id=learners[1].id, topic_id=topic.id, mastery_probability=0.6460, total_answers=1, correct_answers=1),
        TopicMastery(user_id=learners[2].id, topic_id=topic.id, mastery_probability=0.1486, total_answers=1, correct_answers=0),
    ])
    db_session.commit()

    headers = {"Authorization": f"Bearer {instructor_token}"}
    resp = client.get("/api/dashboard/instructor/topics", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    # Find the target topic in topics list
    target = next((t for t in data["topics"] if t["topic_id"] == topic.id), None)
    assert target is not None
    assert target["learners_attempted"] == 3
    assert target["avg_mastery"] == 0.5482
    assert target["accuracy_percent"] == 83.3
    assert target["weak_share_percent"] == 33.3
    assert target["status_counts"] == {"strong": 1, "developing": 1, "weak": 1}

    # Verify not in difficult_topics
    diff_topic_ids = [t["topic_id"] for t in data["difficult_topics"]]
    assert topic.id not in diff_topic_ids


def test_instructor_difficult_topics_rules(client, instructor_token, db_session: Session):
    """Difficult topics rules:

    - Topics with < 5 learners are excluded even if their mastery is lowest.
    - Result sorted by avg_mastery ASC with topic_id ASC tie-break.
    - Capped at 5 topics even if >5 qualify.
    """
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    assert len(topics) >= 8

    # Create 6 learners
    learners = []
    for i in range(1, 7):
        u = User(
            name=f"Difficult Test Learner {i}",
            email=f"diff.learner{i}@example.com",
            password_hash=hash_password("Pass123!"),
            role="learner",
        )
        learners.append(u)
    db_session.add_all(learners)
    db_session.flush()

    masteries = []
    # Topic 0: Extremely low mastery (0.10) but only 3 learners (<5) -> MUST BE EXCLUDED
    for u in learners[:3]:
        masteries.append(TopicMastery(user_id=u.id, topic_id=topics[0].id, mastery_probability=0.10, total_answers=2, correct_answers=0))

    # Topics 1 to 7: Each has 5 learners (qualify with >=5 learners) with defined masteries:
    # T1: 0.35, T2: 0.25, T3: 0.20, T4: 0.40, T5: 0.20 (same as T3, tie-break by topic_id), T6: 0.30, T7: 0.50
    target_masteries = {
        topics[1].id: 0.35,
        topics[2].id: 0.25,
        topics[3].id: 0.20,
        topics[4].id: 0.40,
        topics[5].id: 0.20,
        topics[6].id: 0.30,
        topics[7].id: 0.50,
    }

    for t_id, m_val in target_masteries.items():
        for u in learners[:5]:
            masteries.append(TopicMastery(user_id=u.id, topic_id=t_id, mastery_probability=m_val, total_answers=2, correct_answers=1))

    db_session.add_all(masteries)
    db_session.commit()

    headers = {"Authorization": f"Bearer {instructor_token}"}
    resp = client.get("/api/dashboard/instructor/topics", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    difficult = data["difficult_topics"]
    assert len(difficult) == 5, "Must be capped at top 5 difficult topics"

    # Topic 0 (only 3 learners) must be excluded
    diff_ids = [t["topic_id"] for t in difficult]
    assert topics[0].id not in diff_ids

    # The 7 qualifying topics are:
    # T3 (0.20), T5 (0.20), T2 (0.25), T6 (0.30), T1 (0.35), T4 (0.40), T7 (0.50)
    # Top 5 by avg_mastery ASC then topic_id ASC must be:
    # 1st and 2nd: T3 and T5 ordered by topic_id ASC
    # 3rd: T2 (0.25)
    # 4th: T6 (0.30)
    # 5th: T1 (0.35)
    expected_first_two = sorted([topics[3].id, topics[5].id])
    assert diff_ids[0] == expected_first_two[0]
    assert diff_ids[1] == expected_first_two[1]
    assert diff_ids[2] == topics[2].id
    assert diff_ids[3] == topics[6].id
    assert diff_ids[4] == topics[1].id

    # Confirm ASC order of masteries
    masteries_in_diff = [t["avg_mastery"] for t in difficult]
    assert masteries_in_diff == sorted(masteries_in_diff)


def test_instructor_quiz_average_is_mean_of_attempt_percentages(client, instructor_token, db_session: Session):
    """Mean of per-attempt score percentages:

    Attempts: 6/8 (75.0%), 14/20 (70.0%), 3/8 (37.5%).
    Mean = (75.0 + 70.0 + 37.5)/3 = 60.833... -> 60.8%.
    (Pooled would be 23/36 = 63.88% -> 63.9%, which is explicitly NOT used).
    Also checks course overview breakdown and empty course.
    """
    courses = db_session.query(Course).order_by(Course.id.asc()).all()
    c1, c2, c3, c4 = courses[:4]

    u = User(
        name="Quiz Test Learner",
        email="quiz.learner@example.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(u)
    db_session.flush()

    now = datetime.now(timezone.utc)
    # All 3 attempts belong to course c1
    db_session.add_all([
        QuizAttempt(user_id=u.id, course_id=c1.id, mode="adaptive", status="completed", score=6, total_questions=8, started_at=now, completed_at=now),
        QuizAttempt(user_id=u.id, course_id=c1.id, mode="fixed", status="completed", score=14, total_questions=20, started_at=now, completed_at=now),
        QuizAttempt(user_id=u.id, course_id=c1.id, mode="adaptive", status="completed", score=3, total_questions=8, started_at=now, completed_at=now),
    ])
    db_session.commit()

    headers = {"Authorization": f"Bearer {instructor_token}"}

    # 1. Check /learners
    resp_l = client.get("/api/dashboard/instructor/learners", headers=headers)
    assert resp_l.status_code == status.HTTP_200_OK
    learner_item = next(item for item in resp_l.json()["items"] if item["user_id"] == u.id)
    assert learner_item["completed_attempts"] == 3
    assert learner_item["avg_quiz_percentage"] == 60.8
    assert learner_item["avg_quiz_percentage"] != 63.9

    # 2. Check /overview
    resp_ov = client.get("/api/dashboard/instructor/overview", headers=headers)
    assert resp_ov.status_code == status.HTTP_200_OK
    ov = resp_ov.json()
    assert ov["avg_quiz_percentage"] == 60.8
    assert ov["avg_quiz_percentage"] != 63.9
    assert ov["completed_attempts"] == 3
    assert ov["active_learners"] == 1

    # Check courses in /overview: c1 has 3 attempts, c2 has 0
    c1_ov = next(c for c in ov["courses"] if c["course_id"] == c1.id)
    assert c1_ov["active_learners"] == 1
    assert c1_ov["completed_attempts"] == 3
    assert c1_ov["avg_quiz_percentage"] == 60.8

    c2_ov = next(c for c in ov["courses"] if c["course_id"] == c2.id)
    assert c2_ov["active_learners"] == 0
    assert c2_ov["completed_attempts"] == 0
    assert c2_ov["avg_quiz_percentage"] is None


def test_instructor_learners_no_fanout(client, instructor_token, test_instructor, db_session: Session):
    """Learners table prevents fan-out:

    A learner with 3 attempted topics and 3 completed attempts must report
    attempted_topics == 3 (NOT 9).
    Also checks inactive learner, instructor exclusion, display field name, and last_active fallback.
    """
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()
    t1, t2, t3 = topics[:3]

    active_u = User(
        name="Active Learner Name",
        email="active.learner@example.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    inactive_u = User(
        name="Inactive Learner Name",
        email="inactive.learner@example.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add_all([active_u, inactive_u])
    db_session.flush()

    # 3 attempted topics
    db_session.add_all([
        TopicMastery(user_id=active_u.id, topic_id=t1.id, mastery_probability=0.80, total_answers=2, correct_answers=2),
        TopicMastery(user_id=active_u.id, topic_id=t2.id, mastery_probability=0.60, total_answers=2, correct_answers=1),
        TopicMastery(user_id=active_u.id, topic_id=t3.id, mastery_probability=0.40, total_answers=2, correct_answers=1),
    ])

    now = datetime.now(timezone.utc)
    t_start = now - timedelta(days=1)
    # 3 completed attempts, one with completed_at NULL
    db_session.add_all([
        QuizAttempt(user_id=active_u.id, course_id=t1.course_id, topic_id=t1.id, mode="adaptive", status="completed", score=7, total_questions=8, started_at=now, completed_at=now),
        QuizAttempt(user_id=active_u.id, course_id=t2.course_id, topic_id=t2.id, mode="adaptive", status="completed", score=8, total_questions=8, started_at=now, completed_at=now),
        QuizAttempt(user_id=active_u.id, course_id=t3.course_id, topic_id=t3.id, mode="adaptive", status="completed", score=6, total_questions=8, started_at=t_start, completed_at=None),
    ])
    db_session.commit()

    headers = {"Authorization": f"Bearer {instructor_token}"}
    resp = client.get("/api/dashboard/instructor/learners", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    items = data["items"]
    # Instructor must NOT appear in learners table
    user_ids = [it["user_id"] for it in items]
    assert test_instructor.id not in user_ids

    # Find active learner
    act_it = next(it for it in items if it["user_id"] == active_u.id)
    assert act_it["attempted_topics"] == 3, "Must be exactly 3, not multiplied by 3 attempts (no fanout)"
    assert act_it["completed_attempts"] == 3
    assert act_it["name"] == "Active Learner Name"
    assert act_it["avg_mastery_attempted"] == 0.6000
    assert act_it["avg_quiz_percentage"] is not None
    assert act_it["last_active"] is not None

    # Find inactive learner
    inact_it = next(it for it in items if it["user_id"] == inactive_u.id)
    assert inact_it["name"] == "Inactive Learner Name"
    assert inact_it["attempted_topics"] == 0
    assert inact_it["completed_attempts"] == 0
    assert inact_it["avg_mastery_attempted"] is None
    assert inact_it["avg_quiz_percentage"] is None
    assert inact_it["last_active"] is None


def test_instructor_excludes_in_progress_and_instructor_data(client, instructor_token, test_instructor, db_session: Session):
    """In-progress adaptive attempts, instructor attempts/mastery, and total_answers=0 mastery rows are excluded."""
    topic = db_session.query(Topic).first()

    learner = User(
        name="Valid Learner",
        email="valid.learner@example.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(learner)
    db_session.flush()

    now = datetime.now(timezone.utc)

    # 1. In-progress attempt for learner
    db_session.add(
        QuizAttempt(user_id=learner.id, course_id=topic.course_id, topic_id=topic.id, mode="adaptive", status="in_progress", score=0, total_questions=8, started_at=now, completed_at=None)
    )

    # 2. TopicMastery with total_answers = 0
    db_session.add(
        TopicMastery(user_id=learner.id, topic_id=topic.id, mastery_probability=0.99, total_answers=0, correct_answers=0)
    )

    # 3. Instructor's attempts and mastery (must be completely ignored)
    db_session.add_all([
        TopicMastery(user_id=test_instructor.id, topic_id=topic.id, mastery_probability=0.99, total_answers=10, correct_answers=10),
        QuizAttempt(user_id=test_instructor.id, course_id=topic.course_id, topic_id=topic.id, mode="adaptive", status="completed", score=8, total_questions=8, started_at=now, completed_at=now),
    ])
    db_session.commit()

    headers = {"Authorization": f"Bearer {instructor_token}"}

    # /overview
    ov = client.get("/api/dashboard/instructor/overview", headers=headers).json()
    assert ov["active_learners"] == 0
    assert ov["completed_attempts"] == 0
    assert ov["avg_quiz_percentage"] is None
    assert ov["avg_mastery_attempted"] is None

    # /learners
    learners_data = client.get("/api/dashboard/instructor/learners", headers=headers).json()
    l_item = next(it for it in learners_data["items"] if it["user_id"] == learner.id)
    assert l_item["attempted_topics"] == 0
    assert l_item["completed_attempts"] == 0

    # /topics
    topics_data = client.get("/api/dashboard/instructor/topics", headers=headers).json()
    t_item = next(it for it in topics_data["topics"] if it["topic_id"] == topic.id)
    assert t_item["learners_attempted"] == 0


def test_instructor_empty_platform(client, instructor_token, db_session: Session):
    """Empty platform (zero learners): zeros, nulls, no ZeroDivisionErrors."""
    headers = {"Authorization": f"Bearer {instructor_token}"}

    # /overview
    ov = client.get("/api/dashboard/instructor/overview", headers=headers).json()
    assert ov["total_learners"] == 0
    assert ov["active_learners"] == 0
    assert ov["completed_attempts"] == 0
    assert ov["avg_quiz_percentage"] is None
    assert ov["avg_mastery_attempted"] is None
    for c in ov["courses"]:
        assert c["active_learners"] == 0
        assert c["completed_attempts"] == 0
        assert c["avg_quiz_percentage"] is None

    # /learners
    learners_data = client.get("/api/dashboard/instructor/learners", headers=headers).json()
    assert learners_data["items"] == []

    # /topics
    topics_data = client.get("/api/dashboard/instructor/topics", headers=headers).json()
    assert len(topics_data["topics"]) == 24
    for t in topics_data["topics"]:
        assert t["learners_attempted"] == 0
        assert t["avg_mastery"] is None
        assert t["accuracy_percent"] is None
        assert t["weak_share_percent"] is None
        assert t["status_counts"] == {"strong": 0, "developing": 0, "weak": 0}
    assert topics_data["difficult_topics"] == []


def test_instructor_authorization(client, learner_token, instructor_token):
    """Auth checks: 401 without token, 403 with learner token, 200 with instructor token."""
    endpoints = [
        "/api/dashboard/instructor/overview",
        "/api/dashboard/instructor/learners",
        "/api/dashboard/instructor/topics",
    ]

    for ep in endpoints:
        # Unauthenticated -> 401
        assert client.get(ep).status_code == status.HTTP_401_UNAUTHORIZED

        # Learner token -> 403 Forbidden
        resp_learner = client.get(ep, headers={"Authorization": f"Bearer {learner_token}"})
        assert resp_learner.status_code == status.HTTP_403_FORBIDDEN

        # Instructor token -> 200 OK
        resp_inst = client.get(ep, headers={"Authorization": f"Bearer {instructor_token}"})
        assert resp_inst.status_code == status.HTTP_200_OK


def test_instructor_query_count_independent_of_learner_count(client, instructor_token, db_session: Session):
    """Query counts for all 3 endpoints are constant and independent of learner count (3 vs 30)."""
    from tests.conftest import test_engine

    headers = {"Authorization": f"Bearer {instructor_token}"}
    topics = db_session.query(Topic).order_by(Topic.id.asc()).all()

    def run_endpoints_and_count_queries():
        endpoints = [
            "/api/dashboard/instructor/overview",
            "/api/dashboard/instructor/learners",
            "/api/dashboard/instructor/topics",
        ]
        counts = {}
        for ep in endpoints:
            c = 0
            def listener(conn, cursor, statement, parameters, context, executemany):
                nonlocal c
                c += 1

            event.listen(test_engine, "before_cursor_execute", listener)
            try:
                resp = client.get(ep, headers=headers)
                assert resp.status_code == status.HTTP_200_OK
            finally:
                event.remove(test_engine, "before_cursor_execute", listener)
            counts[ep] = c
        return counts

    # Phase 1: 3 learners
    learners_3 = []
    for i in range(1, 4):
        learners_3.append(User(name=f"L3_{i}", email=f"l3_{i}@example.com", password_hash=hash_password("Pass123!"), role="learner"))
    db_session.add_all(learners_3)
    db_session.flush()

    now = datetime.now(timezone.utc)
    for u in learners_3:
        db_session.add(TopicMastery(user_id=u.id, topic_id=topics[0].id, mastery_probability=0.7, total_answers=2, correct_answers=1))
        db_session.add(QuizAttempt(user_id=u.id, course_id=topics[0].course_id, topic_id=topics[0].id, mode="adaptive", status="completed", score=6, total_questions=8, started_at=now, completed_at=now))
    db_session.commit()

    counts_3 = run_endpoints_and_count_queries()

    # Phase 2: Add 27 more learners -> total 30 learners
    learners_27 = []
    for i in range(4, 31):
        learners_27.append(User(name=f"L30_{i}", email=f"l30_{i}@example.com", password_hash=hash_password("Pass123!"), role="learner"))
    db_session.add_all(learners_27)
    db_session.flush()

    for u in learners_27:
        db_session.add(TopicMastery(user_id=u.id, topic_id=topics[0].id, mastery_probability=0.7, total_answers=2, correct_answers=1))
        db_session.add(QuizAttempt(user_id=u.id, course_id=topics[0].course_id, topic_id=topics[0].id, mode="adaptive", status="completed", score=6, total_questions=8, started_at=now, completed_at=now))
    db_session.commit()

    counts_30 = run_endpoints_and_count_queries()

    print("\n[QUERY COUNTS COMPARISON]")
    for ep in counts_3:
        print(f"  {ep}: {counts_3[ep]} queries with 3 learners == {counts_30[ep]} queries with 30 learners")
        assert counts_3[ep] == counts_30[ep], f"Query count changed for {ep}: {counts_3[ep]} vs {counts_30[ep]}"

