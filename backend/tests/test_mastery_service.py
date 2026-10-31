"""Integration tests for mastery service and BKT integration in quiz submissions.

Follows docs/KNOWLEDGE_MODEL.md Sections 5, 6, and 7.
Tests row locking, persistence, independent BKT recomputations, history chains,
idempotency, and isolation across learners.
"""

from datetime import datetime, timezone
import pytest
from fastapi import status

from app.config import bkt as bkt_config
from app.models.course import Course
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.services.bkt import apply_answers
from app.services.mastery import (
    apply_attempt,
    get_or_create_topic_mastery,
    get_topic_mastery_history,
    get_user_mastery_for_topic,
    get_user_mastery_rows,
)
from app.utils.jwt import create_access_token
from app.utils.security import hash_password


def test_quiz_submission_updates_topic_mastery(client, test_learner, learner_token, db_session):
    """Submitting a quiz creates one TopicMastery row per topic answered, matching answer counts."""
    course = db_session.query(Course).first()
    assert course is not None

    # Pick 2 topics with questions
    topics = db_session.query(Topic).filter(Topic.course_id == course.id).limit(2).all()
    assert len(topics) == 2
    t1, t2 = topics[0], topics[1]

    q1_list = db_session.query(Question).filter(Question.topic_id == t1.id).limit(2).all()
    q2_list = db_session.query(Question).filter(Question.topic_id == t2.id).limit(2).all()
    assert len(q1_list) == 2 and len(q2_list) == 2

    q1_a, q1_b = q1_list[0], q1_list[1]
    q2_a, q2_b = q2_list[0], q2_list[1]

    # Deliberate wrong answer for q1_b
    wrong_for_q1_b = "B" if q1_b.correct_answer.upper() == "A" else "A"

    submission_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": q1_a.id, "selected_answer": q1_a.correct_answer},  # T1: Correct
            {"question_id": q1_b.id, "selected_answer": wrong_for_q1_b},       # T1: Wrong
            {"question_id": q2_a.id, "selected_answer": q2_a.correct_answer},  # T2: Correct
            {"question_id": q2_b.id, "selected_answer": q2_b.correct_answer},  # T2: Correct
        ],
    }

    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/submit", json=submission_payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    # Verify TopicMastery in DB for test_learner
    mastery_rows = get_user_mastery_rows(db_session, test_learner.id, course_id=course.id)
    assert len(mastery_rows) == 2

    m1 = get_user_mastery_for_topic(db_session, test_learner.id, t1.id)
    m2 = get_user_mastery_for_topic(db_session, test_learner.id, t2.id)

    assert m1 is not None
    assert m1.total_answers == 2
    assert m1.correct_answers == 1
    assert m1.last_answered_at is not None

    assert m2 is not None
    assert m2.total_answers == 2
    assert m2.correct_answers == 2
    assert m2.last_answered_at is not None


def test_mastery_probability_matches_bkt_recomputation(client, test_learner, learner_token, db_session):
    """Topic mastery probability matches an independent BKT recomputation in submission order."""
    course = db_session.query(Course).first()
    topics = db_session.query(Topic).filter(Topic.course_id == course.id).limit(2).all()
    t1, t2 = topics[0], topics[1]

    q1_list = db_session.query(Question).filter(Question.topic_id == t1.id).limit(2).all()
    q2_list = db_session.query(Question).filter(Question.topic_id == t2.id).limit(2).all()
    q1_a, q1_b = q1_list[0], q1_list[1]
    q2_a, q2_b = q2_list[0], q2_list[1]

    wrong_for_q1_b = "B" if q1_b.correct_answer.upper() == "A" else "A"

    submission_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": q1_a.id, "selected_answer": q1_a.correct_answer},  # T1: Correct
            {"question_id": q2_a.id, "selected_answer": q2_a.correct_answer},  # T2: Correct
            {"question_id": q1_b.id, "selected_answer": wrong_for_q1_b},       # T1: Wrong
            {"question_id": q2_b.id, "selected_answer": q2_b.correct_answer},  # T2: Correct
        ],
    }

    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/submit", json=submission_payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    # Independent BKT recomputation
    # Topic 1 received: q1_a (correct), then q1_b (wrong)
    expected_p1 = apply_answers(
        bkt_config.P_INIT,
        [(True, q1_a.difficulty), (False, q1_b.difficulty)]
    )
    # Topic 2 received: q2_a (correct), then q2_b (correct)
    expected_p2 = apply_answers(
        bkt_config.P_INIT,
        [(True, q2_a.difficulty), (True, q2_b.difficulty)]
    )

    m1 = get_user_mastery_for_topic(db_session, test_learner.id, t1.id)
    m2 = get_user_mastery_for_topic(db_session, test_learner.id, t2.id)

    assert m1.mastery_probability == pytest.approx(expected_p1, abs=1e-4)
    assert m2.mastery_probability == pytest.approx(expected_p2, abs=1e-4)

    # Check History records
    attempt_id = resp.json()["attempt_id"]
    h1 = (
        db_session.query(TopicMasteryHistory)
        .filter_by(attempt_id=attempt_id, topic_id=t1.id)
        .one()
    )
    assert h1.mastery_before == pytest.approx(bkt_config.P_INIT, abs=1e-4)
    assert h1.mastery_after == pytest.approx(expected_p1, abs=1e-4)
    assert h1.answers_in_attempt == 2
    assert h1.correct_in_attempt == 1

    h2 = (
        db_session.query(TopicMasteryHistory)
        .filter_by(attempt_id=attempt_id, topic_id=t2.id)
        .one()
    )
    assert h2.mastery_before == pytest.approx(bkt_config.P_INIT, abs=1e-4)
    assert h2.mastery_after == pytest.approx(expected_p2, abs=1e-4)
    assert h2.answers_in_attempt == 2
    assert h2.correct_in_attempt == 2


def test_second_quiz_updates_rows_and_creates_second_history(client, test_learner, learner_token, db_session):
    """Submitting a second quiz updates existing TopicMastery rows without duplicates and appends history."""
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    questions = db_session.query(Question).filter(Question.topic_id == topic.id).limit(2).all()
    q1, q2 = questions[0], questions[1]

    headers = {"Authorization": f"Bearer {learner_token}"}

    # Quiz 1: 2 correct answers
    payload_1 = {
        "course_id": course.id,
        "answers": [
            {"question_id": q1.id, "selected_answer": q1.correct_answer},
            {"question_id": q2.id, "selected_answer": q2.correct_answer},
        ],
    }
    r1 = client.post("/api/quiz/submit", json=payload_1, headers=headers)
    assert r1.status_code == status.HTTP_200_OK
    attempt_1_id = r1.json()["attempt_id"]

    m_after_q1 = get_user_mastery_for_topic(db_session, test_learner.id, topic.id)
    p_after_q1 = m_after_q1.mastery_probability
    assert m_after_q1.total_answers == 2

    # Quiz 2: 1 wrong answer
    wrong_ans = "B" if q1.correct_answer.upper() == "A" else "A"
    payload_2 = {
        "course_id": course.id,
        "answers": [
            {"question_id": q1.id, "selected_answer": wrong_ans},
        ],
    }
    r2 = client.post("/api/quiz/submit", json=payload_2, headers=headers)
    assert r2.status_code == status.HTTP_200_OK
    attempt_2_id = r2.json()["attempt_id"]

    # Exactly 1 TopicMastery row (no duplicates)
    all_rows = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .all()
    )
    assert len(all_rows) == 1
    m_after_q2 = all_rows[0]
    assert m_after_q2.total_answers == 3
    assert m_after_q2.correct_answers == 2

    # Exactly 2 history rows
    histories = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .order_by(TopicMasteryHistory.id.asc())
        .all()
    )
    assert len(histories) == 2

    h1, h2 = histories[0], histories[1]
    assert h1.attempt_id == attempt_1_id
    assert h1.mastery_before == pytest.approx(bkt_config.P_INIT, abs=1e-4)
    assert h1.mastery_after == pytest.approx(p_after_q1, abs=1e-4)

    assert h2.attempt_id == attempt_2_id
    # History 2 starts where History 1 ended
    assert h2.mastery_before == pytest.approx(p_after_q1, abs=1e-4)
    assert h2.mastery_after == pytest.approx(m_after_q2.mastery_probability, abs=1e-4)
    assert h2.answers_in_attempt == 1
    assert h2.correct_in_attempt == 0


def test_topics_not_in_quiz_get_no_rows(client, test_learner, learner_token, db_session):
    """Topics that were not included in the quiz get no TopicMastery or history rows."""
    course = db_session.query(Course).first()
    course_topics = db_session.query(Topic).filter(Topic.course_id == course.id).all()
    assert len(course_topics) >= 2

    active_topic = course_topics[0]
    unattempted_topic = course_topics[1]

    question = db_session.query(Question).filter(Question.topic_id == active_topic.id).first()

    payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": question.id, "selected_answer": question.correct_answer},
        ],
    }
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/submit", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    active_mastery = get_user_mastery_for_topic(db_session, test_learner.id, active_topic.id)
    assert active_mastery is not None

    unattempted_mastery = get_user_mastery_for_topic(db_session, test_learner.id, unattempted_topic.id)
    assert unattempted_mastery is None

    unattempted_history = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, topic_id=unattempted_topic.id)
        .count()
    )
    assert unattempted_history == 0


def test_two_different_learners_do_not_affect_each_other(client, test_learner, learner_token, db_session):
    """Two learners' mastery states for the same topic remain completely isolated."""
    # Create second learner
    learner_2 = User(
        name="Second Learner",
        email="second.learner@learnwise.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(learner_2)
    db_session.commit()
    db_session.refresh(learner_2)
    learner_2_token = create_access_token(learner_2.id)

    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    question = db_session.query(Question).filter(Question.topic_id == topic.id).first()

    # Learner 1 answers correctly -> higher mastery
    resp_l1 = client.post(
        "/api/quiz/submit",
        json={
            "course_id": course.id,
            "answers": [{"question_id": question.id, "selected_answer": question.correct_answer}],
        },
        headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert resp_l1.status_code == status.HTTP_200_OK

    m_l1_before = get_user_mastery_for_topic(db_session, test_learner.id, topic.id)
    p_l1 = m_l1_before.mastery_probability
    assert p_l1 > bkt_config.P_INIT

    # Learner 2 answers incorrectly -> lower mastery
    wrong_ans = "B" if question.correct_answer.upper() == "A" else "A"
    resp_l2 = client.post(
        "/api/quiz/submit",
        json={
            "course_id": course.id,
            "answers": [{"question_id": question.id, "selected_answer": wrong_ans}],
        },
        headers={"Authorization": f"Bearer {learner_2_token}"}
    )
    assert resp_l2.status_code == status.HTTP_200_OK

    # Re-fetch both
    db_session.refresh(m_l1_before)
    m_l2 = get_user_mastery_for_topic(db_session, learner_2.id, topic.id)

    # Learner 1 is untouched by Learner 2
    assert m_l1_before.mastery_probability == p_l1
    assert m_l1_before.total_answers == 1
    assert m_l1_before.correct_answers == 1

    # Learner 2 has lower mastery
    assert m_l2.mastery_probability < bkt_config.P_INIT
    assert m_l2.total_answers == 1
    assert m_l2.correct_answers == 0


def test_failed_submission_creates_no_attempt_or_mastery(client, test_learner, learner_token, db_session):
    """A submission failing validation creates no QuizAttempt, no QuizResponse, and no TopicMastery."""
    course = db_session.query(Course).first()
    question = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == course.id)
        .first()
    )

    headers = {"Authorization": f"Bearer {learner_token}"}

    # 1. Duplicate question submission
    dup_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": question.id, "selected_answer": "A"},
            {"question_id": question.id, "selected_answer": "B"},
        ],
    }
    r_dup = client.post("/api/quiz/submit", json=dup_payload, headers=headers)
    assert r_dup.status_code == status.HTTP_400_BAD_REQUEST

    assert db_session.query(QuizAttempt).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(QuizResponse).count() == 0
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 0

    # 2. Foreign question from another course
    courses = db_session.query(Course).order_by(Course.id).all()
    c1, c2 = courses[0], courses[1]
    foreign_q = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == c2.id)
        .first()
    )

    wrong_course_payload = {
        "course_id": c1.id,
        "answers": [
            {"question_id": foreign_q.id, "selected_answer": "A"},
        ],
    }
    r_foreign = client.post("/api/quiz/submit", json=wrong_course_payload, headers=headers)
    assert r_foreign.status_code == status.HTTP_400_BAD_REQUEST

    assert db_session.query(QuizAttempt).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 0


def test_apply_attempt_idempotency_does_not_double_apply(test_learner, db_session):
    """Calling apply_attempt twice for the same attempt is a no-op (idempotent)."""
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    question = db_session.query(Question).filter(Question.topic_id == topic.id).first()

    # Create an attempt manually
    now = datetime.now(timezone.utc)
    attempt = QuizAttempt(
        user_id=test_learner.id,
        course_id=course.id,
        quiz_type="INITIAL",
        mode="fixed",
        status="completed",
        score=1,
        total_questions=1,
        started_at=now,
        completed_at=now,
    )
    db_session.add(attempt)
    db_session.flush()

    response = QuizResponse(
        attempt_id=attempt.id,
        question_id=question.id,
        topic_id=topic.id,
        selected_answer=question.correct_answer,
        is_correct=True,
    )
    db_session.add(response)
    db_session.flush()

    # 1. First execution
    apply_attempt(db_session, test_learner.id, attempt, [response])
    db_session.commit()

    mastery_first = get_user_mastery_for_topic(db_session, test_learner.id, topic.id)
    p_first = mastery_first.mastery_probability
    answers_first = mastery_first.total_answers
    history_count_first = (
        db_session.query(TopicMasteryHistory)
        .filter_by(attempt_id=attempt.id, topic_id=topic.id)
        .count()
    )
    assert answers_first == 1
    assert history_count_first == 1

    # 2. Second execution (must be a no-op)
    apply_attempt(db_session, test_learner.id, attempt, [response])
    db_session.commit()

    db_session.refresh(mastery_first)
    assert mastery_first.mastery_probability == p_first
    assert mastery_first.total_answers == answers_first
    assert (
        db_session.query(TopicMasteryHistory)
        .filter_by(attempt_id=attempt.id, topic_id=topic.id)
        .count()
    ) == history_count_first


def test_apply_attempt_failure_atomically_rolls_back_submission(
    client, test_learner, learner_token, db_session, monkeypatch
):
    """When apply_attempt raises an exception, the entire submission transaction rolls back.

    Asserts:
      (a) Request fails with a 5xx status code.
      (b) Zero rows in quiz_attempts, quiz_responses, topic_mastery, and topic_mastery_history.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    course = db_session.query(Course).first()
    question = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == course.id)
        .first()
    )

    def failing_apply_attempt(*args, **kwargs):
        raise RuntimeError("Simulated failure in mastery service during submission")

    # Monkeypatch apply_attempt in app.routes.quiz where submit_quiz imports it
    monkeypatch.setattr("app.routes.quiz.apply_attempt", failing_apply_attempt)

    headers = {"Authorization": f"Bearer {learner_token}"}
    payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": question.id, "selected_answer": question.correct_answer},
        ],
    }

    # Use TestClient with raise_server_exceptions=False to capture the 500 HTTP response
    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        resp = no_raise_client.post("/api/quiz/submit", json=payload, headers=headers)
        assert resp.status_code >= 500

    # Assert complete atomic rollback: 0 rows created for this user
    assert db_session.query(QuizAttempt).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(QuizResponse).count() == 0
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 0


def test_get_or_create_topic_mastery_concurrent_insert_race(test_learner, db_session):
    """Simulates simultaneous first submissions hitting the unique constraint.

    Verifies the savepoint catches IntegrityError, re-selects with FOR UPDATE,
    and returns without raising an exception or duplicating rows.
    """
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()

    # Pre-condition: test_learner has no TopicMastery for topic
    assert get_user_mastery_for_topic(db_session, test_learner.id, topic.id) is None

    # Simulate race: right when get_or_create_topic_mastery is about to add/flush the new row,
    # another connection pre-inserts the conflicting row and commits it.
    orig_add = db_session.add

    def race_add(instance):
        if (
            isinstance(instance, TopicMastery)
            and instance.user_id == test_learner.id
            and instance.topic_id == topic.id
        ):
            with db_session.bind.connect() as conn:
                conn.execute(
                    TopicMastery.__table__.insert().values(
                        user_id=test_learner.id,
                        topic_id=topic.id,
                        mastery_probability=bkt_config.P_INIT,
                        total_answers=0,
                        correct_answers=0,
                    )
                )
                conn.commit()
        orig_add(instance)

    db_session.add = race_add
    try:
        mastery = get_or_create_topic_mastery(db_session, test_learner.id, topic.id)
        assert mastery is not None
        assert mastery.user_id == test_learner.id
        assert mastery.topic_id == topic.id
    finally:
        db_session.add = orig_add

    # Confirm exactly 1 row exists (no duplicate and no exception)
    rows = db_session.query(TopicMastery).filter_by(user_id=test_learner.id, topic_id=topic.id).all()
    assert len(rows) == 1

    # Calling get_or_create_topic_mastery a second time returns the same row
    second_call = get_or_create_topic_mastery(db_session, test_learner.id, topic.id)
    assert second_call.id == mastery.id
    assert len(db_session.query(TopicMastery).filter_by(user_id=test_learner.id, topic_id=topic.id).all()) == 1

