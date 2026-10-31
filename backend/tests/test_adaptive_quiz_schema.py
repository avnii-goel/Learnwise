from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.adaptive_quiz_step import AdaptiveQuizStep


def test_quiz_attempt_defaults_and_check_constraints(db_session, test_learner):
    """New QuizAttempt rows default to mode='fixed' and status='completed', and enforce CHECK constraints."""
    course = db_session.query(Course).first()
    assert course is not None

    # 1. Default column values
    attempt = QuizAttempt(
        user_id=test_learner.id,
        course_id=course.id,
        score=10,
        total_questions=20,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)

    assert attempt.mode == "fixed"
    assert attempt.status == "completed"
    assert attempt.topic_id is None

    # 2. Invalid mode violates CHECK constraint
    invalid_mode_attempt = QuizAttempt(
        user_id=test_learner.id,
        course_id=course.id,
        mode="invalid_mode",
        status="completed",
        score=0,
        total_questions=8,
    )
    db_session.add(invalid_mode_attempt)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 3. Invalid status violates CHECK constraint
    invalid_status_attempt = QuizAttempt(
        user_id=test_learner.id,
        course_id=course.id,
        mode="adaptive",
        status="invalid_status",
        score=0,
        total_questions=8,
    )
    db_session.add(invalid_status_attempt)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_partial_unique_index_adaptive_in_progress(db_session, test_learner):
    """The partial unique index rejects a second in_progress adaptive attempt for the same (user, topic)."""
    topic = db_session.query(Topic).first()
    assert topic is not None

    # 1. First in_progress adaptive attempt succeeds
    attempt1 = QuizAttempt(
        user_id=test_learner.id,
        course_id=topic.course_id,
        topic_id=topic.id,
        mode="adaptive",
        status="in_progress",
        score=0,
        total_questions=8,
    )
    db_session.add(attempt1)
    db_session.commit()

    # 2. Second in_progress adaptive attempt for SAME user and topic must fail
    attempt2 = QuizAttempt(
        user_id=test_learner.id,
        course_id=topic.course_id,
        topic_id=topic.id,
        mode="adaptive",
        status="in_progress",
        score=0,
        total_questions=8,
    )
    db_session.add(attempt2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 3. An in_progress attempt for a DIFFERENT topic succeeds
    other_topic = db_session.query(Topic).filter(Topic.id != topic.id).first()
    assert other_topic is not None
    attempt_other_topic = QuizAttempt(
        user_id=test_learner.id,
        course_id=other_topic.course_id,
        topic_id=other_topic.id,
        mode="adaptive",
        status="in_progress",
        score=0,
        total_questions=8,
    )
    db_session.add(attempt_other_topic)
    db_session.commit()

    # 4. Once attempt1 is completed, a new in_progress attempt for topic is permitted
    db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt1.id).update({"status": "completed"})
    db_session.commit()

    attempt3 = QuizAttempt(
        user_id=test_learner.id,
        course_id=topic.course_id,
        topic_id=topic.id,
        mode="adaptive",
        status="in_progress",
        score=0,
        total_questions=8,
    )
    db_session.add(attempt3)
    db_session.commit()

    # 5. Multiple completed adaptive attempts for the same topic can coexist
    db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt3.id).update({"status": "completed"})
    db_session.commit()

    attempt4 = QuizAttempt(
        user_id=test_learner.id,
        course_id=topic.course_id,
        topic_id=topic.id,
        mode="adaptive",
        status="completed",
        score=7,
        total_questions=8,
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(attempt4)
    db_session.commit()


def test_adaptive_quiz_steps_unique_constraints(db_session, test_learner):
    """UNIQUE (attempt_id, step_number) and UNIQUE (attempt_id, question_id) constraints work."""
    topic = db_session.query(Topic).first()
    assert topic is not None
    questions = db_session.query(Question).filter(Question.topic_id == topic.id).limit(2).all()
    assert len(questions) >= 2
    q1, q2 = questions[0], questions[1]

    attempt = QuizAttempt(
        user_id=test_learner.id,
        course_id=topic.course_id,
        topic_id=topic.id,
        mode="adaptive",
        status="in_progress",
        score=0,
        total_questions=8,
    )
    db_session.add(attempt)
    db_session.commit()

    # Add step 1
    step1 = AdaptiveQuizStep(
        attempt_id=attempt.id,
        step_number=1,
        question_id=q1.id,
        target_difficulty="easy",
        served_difficulty="easy",
        selection_reason="unseen_at_target",
        mastery_before=0.30,
    )
    db_session.add(step1)
    db_session.commit()

    # 1. Duplicate step_number on the same attempt must fail
    dup_step_num = AdaptiveQuizStep(
        attempt_id=attempt.id,
        step_number=1,
        question_id=q2.id,
        target_difficulty="easy",
        served_difficulty="easy",
        selection_reason="unseen_at_target",
        mastery_before=0.30,
    )
    db_session.add(dup_step_num)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 2. Duplicate question_id on the same attempt must fail
    dup_question = AdaptiveQuizStep(
        attempt_id=attempt.id,
        step_number=2,
        question_id=q1.id,
        target_difficulty="easy",
        served_difficulty="easy",
        selection_reason="unseen_at_target",
        mastery_before=0.30,
    )
    db_session.add(dup_question)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # 3. Valid distinct step and distinct question succeeds
    step2 = AdaptiveQuizStep(
        attempt_id=attempt.id,
        step_number=2,
        question_id=q2.id,
        target_difficulty="medium",
        served_difficulty="medium",
        selection_reason="unseen_at_target",
        mastery_before=0.6182,
    )
    db_session.add(step2)
    db_session.commit()

    assert step1.id is not None
    assert step2.id is not None
    assert step2.step_number == 2


def test_existing_fixed_quiz_behavior_unchanged(client, learner_token, db_session):
    """Existing fixed 20-question course quiz remains unchanged and persists with mode='fixed', status='completed'."""
    course = db_session.query(Course).first()
    assert course is not None

    headers = {"Authorization": f"Bearer {learner_token}"}
    gen_resp = client.post(f"/api/quiz/generate/course/{course.id}", headers=headers)
    assert gen_resp.status_code == 200
    questions = gen_resp.json()["questions"]
    assert len(questions) == 20

    submission_payload = {
        "course_id": course.id,
        "answers": [{"question_id": q["question_id"], "selected_answer": "A"} for q in questions],
    }
    sub_resp = client.post("/api/quiz/submit", json=submission_payload, headers=headers)
    assert sub_resp.status_code == 200
    result = sub_resp.json()
    attempt_id = result["attempt_id"]

    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    assert attempt is not None
    assert attempt.mode == "fixed"
    assert attempt.status == "completed"
    assert attempt.topic_id is None
    assert attempt.total_questions == 20

