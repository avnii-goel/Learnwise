"""End-to-end simulation, repeat/supply exhaustion, and logging integrity tests.

Reference: docs/ADAPTIVE_QUIZ.md Sections 3-11.
Verifies:
(a) Simulated GOOD and BAD learners using the real endpoints and test DB.
(b) Three consecutive adaptive quizzes on the same topic under question supply constraints.
(c) BKT replay consistency against stored TopicMastery and step mastery_after.
(d) Database logging integrity for both adaptive and fixed quiz modes.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.config.bkt import P_INIT
from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.adaptive_quiz_step import AdaptiveQuizStep
from app.models.topic_mastery import TopicMastery
from app.models.user import User
from app.services.bkt import update_mastery
from app.utils.jwt import create_access_token
from app.utils.security import hash_password


DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}


@pytest.fixture
def ample_topic(db_session: Session) -> Topic:
    """Creates a temporary topic with at least 8 easy, 8 medium, and 8 hard questions (24 total).

    Ensures question supply never constrains difficulty progression during simulation.
    """
    course = Course(
        title="Simulation Disposable Course",
        description="Course providing sufficient difficulty questions for E2E tests",
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    topic = Topic(
        title="Simulation Ample Topic",
        description="Topic containing 8 easy, 8 medium, and 8 hard questions",
        course_id=course.id,
        order=1,
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    # Seed 8 easy, 8 medium, and 8 hard questions
    for diff in ["easy", "medium", "hard"]:
        for i in range(1, 9):
            q = Question(
                topic_id=topic.id,
                question_text=f"Question {diff.upper()} #{i} for topic {topic.id}",
                option_a=f"{diff} choice A",
                option_b=f"{diff} choice B",
                option_c=f"{diff} choice C",
                option_d=f"{diff} choice D",
                correct_answer="A",
                difficulty=diff.capitalize(),
            )
            db_session.add(q)

    db_session.commit()
    return topic


def create_simulated_user(db_session: Session, name: str, email: str) -> tuple[User, str]:
    """Helper to register and generate a JWT access token for a simulated learner."""
    user = User(
        name=name,
        email=email,
        password_hash=hash_password("SimulationPass123!"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token(user.id)
    return user, token


def test_adaptive_simulation_good_learner(client, db_session, ample_topic):
    """(a) GOOD learner: fresh topic, always correct, 8 answers.

    Asserts from adaptive_quiz_steps:
    - First served difficulty is easy.
    - Served difficulty sequence never decreases.
    - Hard difficulty is reached.
    - No question is repeated.
    """
    _, token = create_simulated_user(db_session, "Good Learner", "good.learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Start adaptive quiz
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": ample_topic.id}, headers=headers)
    assert start_resp.status_code == status.HTTP_201_CREATED
    data = start_resp.json()
    attempt_id = data["attempt_id"]
    curr_qid = data["question"]["question_id"]

    # Answer all 8 questions correctly
    for step in range(1, 9):
        q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
        assert q_obj is not None

        # Always submit correct answer
        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": q_obj.correct_answer},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        ans_data = ans_resp.json()

        if step < 8:
            assert ans_data["finished"] is False
            curr_qid = ans_data["next_question"]["question_id"]
        else:
            assert ans_data["finished"] is True

    # Inspect persisted adaptive_quiz_steps
    steps = (
        db_session.query(AdaptiveQuizStep)
        .filter(AdaptiveQuizStep.attempt_id == attempt_id)
        .order_by(AdaptiveQuizStep.step_number.asc())
        .all()
    )
    assert len(steps) == 8

    # 1. First served difficulty is easy
    assert steps[0].served_difficulty == "easy"

    # 2. Sequence never decreases
    for i in range(1, len(steps)):
        prev_rank = DIFFICULTY_RANK[steps[i - 1].served_difficulty]
        curr_rank = DIFFICULTY_RANK[steps[i].served_difficulty]
        assert curr_rank >= prev_rank, (
            f"Difficulty decreased from step {i} ({steps[i-1].served_difficulty}) "
            f"to step {i+1} ({steps[i].served_difficulty})"
        )

    # 3. Hard is reached
    served_difficulties = [s.served_difficulty for s in steps]
    assert "hard" in served_difficulties

    # 4. No question repeats
    served_question_ids = [s.question_id for s in steps]
    assert len(set(served_question_ids)) == 8


def test_adaptive_simulation_bad_learner(client, db_session, ample_topic):
    """(a) BAD learner: fresh topic, always wrong, 8 answers.

    Asserts from adaptive_quiz_steps:
    - Every served difficulty is easy.
    - No question is repeated.
    """
    _, token = create_simulated_user(db_session, "Bad Learner", "bad.learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": ample_topic.id}, headers=headers)
    assert start_resp.status_code == status.HTTP_201_CREATED
    data = start_resp.json()
    attempt_id = data["attempt_id"]
    curr_qid = data["question"]["question_id"]

    # Answer all 8 questions incorrectly
    for step in range(1, 9):
        q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
        assert q_obj is not None

        # Pick wrong answer
        wrong_answer = "B" if q_obj.correct_answer.upper() == "A" else "A"
        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": wrong_answer},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        ans_data = ans_resp.json()

        if step < 8:
            assert ans_data["finished"] is False
            curr_qid = ans_data["next_question"]["question_id"]
        else:
            assert ans_data["finished"] is True

    # Inspect persisted adaptive_quiz_steps
    steps = (
        db_session.query(AdaptiveQuizStep)
        .filter(AdaptiveQuizStep.attempt_id == attempt_id)
        .order_by(AdaptiveQuizStep.step_number.asc())
        .all()
    )
    assert len(steps) == 8

    # 1. Every served difficulty is easy
    for step in steps:
        assert step.served_difficulty == "easy", f"Expected easy, got {step.served_difficulty} at step {step.step_number}"

    # 2. No question repeats
    served_question_ids = [s.question_id for s in steps]
    assert len(set(served_question_ids)) == 8


def test_adaptive_repeat_and_exhaustion_three_quizzes(client, db_session):
    """(b) Repeat/supply test: 3 consecutive adaptive quizzes on the same seeded topic (20 questions).

    Asserts:
    - No question repeats inside any single quiz.
    - selection_reason is 'unseen_at_target' or 'unseen_other_level' for as long as unseen questions exist.
    - Each quiz completes with 8 answered steps even when unseen levels run out.
    """
    # Use baseline seeded topic 1 (Network Fundamentals: 20 questions total)
    topic = db_session.query(Topic).first()
    assert topic is not None
    total_catalog_questions = db_session.query(Question).filter(Question.topic_id == topic.id).count()
    assert total_catalog_questions == 20

    user, token = create_simulated_user(db_session, "Repeat Learner", "repeat.learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    all_seen_so_far = set()

    for quiz_idx in range(1, 4):
        start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": topic.id}, headers=headers)
        assert start_resp.status_code == status.HTTP_201_CREATED
        data = start_resp.json()
        attempt_id = data["attempt_id"]
        curr_qid = data["question"]["question_id"]

        # Track questions seen before this quiz started
        seen_before_this_quiz = set(all_seen_so_far)

        # Answer 8 questions
        for step in range(1, 9):
            q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
            selected = q_obj.correct_answer if (step % 2 == 0) else ("B" if q_obj.correct_answer == "A" else "A")

            ans_resp = client.post(
                f"/api/quiz/adaptive/{attempt_id}/answer",
                json={"question_id": curr_qid, "selected_answer": selected},
                headers=headers,
            )
            assert ans_resp.status_code == status.HTTP_200_OK
            ans_data = ans_resp.json()

            if step < 8:
                curr_qid = ans_data["next_question"]["question_id"]

        # Fetch persisted steps for this quiz
        steps = (
            db_session.query(AdaptiveQuizStep)
            .filter(AdaptiveQuizStep.attempt_id == attempt_id)
            .order_by(AdaptiveQuizStep.step_number.asc())
            .all()
        )
        assert len(steps) == 8

        # 1. No question repeats inside this single quiz
        quiz_qids = [s.question_id for s in steps]
        assert len(set(quiz_qids)) == 8

        # 2. Verify selection reasons
        for step_obj in steps:
            # If the question was not seen before this quiz started, it must be selected as unseen
            if step_obj.question_id not in seen_before_this_quiz:
                assert step_obj.selection_reason in ("unseen_at_target", "unseen_other_level"), (
                    f"Quiz {quiz_idx} step {step_obj.step_number}: expected unseen reason for new question "
                    f"{step_obj.question_id}, got {step_obj.selection_reason}"
                )

        # 3. Verify attempt status is completed
        attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
        assert attempt.status == "completed"

        # Update set of all questions seen by this learner across completed attempts
        all_seen_so_far.update(quiz_qids)


def test_adaptive_bkt_replay_consistency(client, db_session, ample_topic):
    """(c) Consistency test: replay answered questions through update_mastery in step order.

    Asserts:
    - Result equals stored TopicMastery.mastery_probability (tolerance 1e-9).
    - Result equals the 8th step's mastery_after.
    """
    user, token = create_simulated_user(db_session, "Replay Learner", "replay.learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": ample_topic.id}, headers=headers)
    assert start_resp.status_code == status.HTTP_201_CREATED
    data = start_resp.json()
    attempt_id = data["attempt_id"]
    curr_qid = data["question"]["question_id"]

    # Pre-determined sequence of answers (alternating correct/incorrect)
    pattern = [True, True, False, True, False, False, True, True]

    for step, is_corr in enumerate(pattern, start=1):
        q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
        selected = q_obj.correct_answer if is_corr else ("B" if q_obj.correct_answer == "A" else "A")

        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": selected},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        ans_data = ans_resp.json()
        if step < 8:
            curr_qid = ans_data["next_question"]["question_id"]

    # Fetch steps in order
    steps = (
        db_session.query(AdaptiveQuizStep)
        .filter(AdaptiveQuizStep.attempt_id == attempt_id)
        .order_by(AdaptiveQuizStep.step_number.asc())
        .all()
    )
    assert len(steps) == 8

    # Replay through canonical update_mastery
    running_p = steps[0].mastery_before
    assert running_p == P_INIT

    for step in steps:
        running_p = update_mastery(running_p, step.is_correct, step.served_difficulty)

    # Query stored TopicMastery
    tm = (
        db_session.query(TopicMastery)
        .filter(TopicMastery.user_id == user.id, TopicMastery.topic_id == ample_topic.id)
        .first()
    )
    assert tm is not None
    assert abs(running_p - float(tm.mastery_probability)) < 1e-9
    assert abs(running_p - float(steps[-1].mastery_after)) < 1e-9


def test_adaptive_and_fixed_logging_integrity(client, db_session, ample_topic):
    """(d) Logging check: mode, status, timestamps, and step rows across adaptive and fixed quizzes."""
    user, token = create_simulated_user(db_session, "Logging Learner", "logging.learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start an in-progress adaptive attempt
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": ample_topic.id}, headers=headers)
    assert start_resp.status_code == status.HTTP_201_CREATED
    adaptive_attempt_id = start_resp.json()["attempt_id"]
    curr_qid = start_resp.json()["question"]["question_id"]

    # In-progress adaptive attempt must strictly have completed_at = NULL
    in_progress_attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == adaptive_attempt_id).first()
    assert in_progress_attempt.status == "in_progress"
    assert in_progress_attempt.completed_at is None

    # Complete 8 questions
    for step in range(1, 9):
        q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
        ans_resp = client.post(
            f"/api/quiz/adaptive/{adaptive_attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": q_obj.correct_answer},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        ans_data = ans_resp.json()
        if step < 8:
            curr_qid = ans_data["next_question"]["question_id"]

    # Finished adaptive attempt must have mode='adaptive', status='completed', and completed_at is not NULL
    adaptive_attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == adaptive_attempt_id).first()
    assert adaptive_attempt.mode == "adaptive"
    assert adaptive_attempt.status == "completed"
    assert adaptive_attempt.completed_at is not None

    adaptive_steps = (
        db_session.query(AdaptiveQuizStep)
        .filter(AdaptiveQuizStep.attempt_id == adaptive_attempt_id)
        .order_by(AdaptiveQuizStep.step_number.asc())
        .all()
    )
    assert len(adaptive_steps) == 8
    for idx, s in enumerate(adaptive_steps, start=1):
        assert s.step_number == idx
        assert s.mastery_after is not None
        assert s.is_correct is not None
        assert s.answered_at is not None

    # 2. Complete a fixed course quiz
    course = db_session.query(Course).first()
    gen_resp = client.post(f"/api/quiz/generate/course/{course.id}", headers=headers)
    assert gen_resp.status_code == status.HTTP_200_OK
    questions = gen_resp.json()["questions"]
    assert len(questions) == 20

    sub_resp = client.post(
        "/api/quiz/submit",
        json={
            "course_id": course.id,
            "answers": [{"question_id": q["question_id"], "selected_answer": "A"} for q in questions],
        },
        headers=headers,
    )
    assert sub_resp.status_code == status.HTTP_200_OK
    fixed_attempt_id = sub_resp.json()["attempt_id"]

    fixed_attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == fixed_attempt_id).first()
    assert fixed_attempt is not None
    assert fixed_attempt.mode == "fixed"
    assert fixed_attempt.status == "completed"
    assert fixed_attempt.completed_at is not None
