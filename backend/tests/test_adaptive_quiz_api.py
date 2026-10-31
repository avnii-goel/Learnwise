"""API integration tests for adaptive quizzing service and endpoints.

Reference: docs/ADAPTIVE_QUIZ.md Sections 6-11.
Tests start/resume lifecycle, question sanitization, 409 conflict detection,
ownership security (404), unauthenticated access (401), catalog constraints,
8-step progression, BKT finalization, atomic rollback, and backfill isolation.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.adaptive_quiz_step import AdaptiveQuizStep
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.utils.jwt import create_access_token
from app.utils.security import hash_password
from app.seeds.backfill_mastery import run_backfill
import app.services.adaptive_service as adaptive_service_mod


@pytest.fixture
def sample_topic(db_session: Session) -> Topic:
    """Returns a baseline topic with seeded questions (at least 8 questions)."""
    topic = db_session.query(Topic).first()
    assert topic is not None
    q_count = db_session.query(Question).filter(Question.topic_id == topic.id).count()
    assert q_count >= 8
    return topic


@pytest.fixture
def second_learner(db_session: Session) -> User:
    """Creates a second learner user for authorization checks."""
    user = User(
        name="Second Learner",
        email="second.learner@learnwise.com",
        password_hash=hash_password("SecondPass123!"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_adaptive_start_returns_201_and_omits_answers_and_difficulty(
    client, learner_token, sample_topic, db_session
):
    """POST /api/quiz/adaptive/start creates a new attempt, returns 201, omits hidden fields."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    assert resp.status_code == status.HTTP_201_CREATED

    data = resp.json()
    assert data["topic_id"] == sample_topic.id
    assert data["mode"] == "adaptive"
    assert data["total_questions"] == 8
    assert data["question_number"] == 1
    assert data["resumed"] is False

    question = data["question"]
    assert "correct_answer" not in question
    assert "difficulty" not in question
    assert "question_id" in question
    assert "question_text" in question
    assert "option_a" in question
    assert "option_b" in question
    assert "option_c" in question
    assert "option_d" in question

    # Verify attempt in DB
    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == data["attempt_id"]).first()
    assert attempt is not None
    assert attempt.mode == "adaptive"
    assert attempt.status == "in_progress"
    assert attempt.quiz_type == "ADAPTIVE"
    assert attempt.completed_at is None


def test_adaptive_completed_at_is_null_for_in_progress(client, learner_token, sample_topic, db_session):
    """An in-progress adaptive attempt must strictly have completed_at = NULL in the DB."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    assert resp.status_code == status.HTTP_201_CREATED

    attempt_id = resp.json()["attempt_id"]
    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    assert attempt.completed_at is None
    assert attempt.status == "in_progress"


def test_adaptive_start_twice_resumes_with_200_and_same_question(
    client, learner_token, sample_topic, db_session
):
    """Calling start again for the same topic returns 200 OK, resumed=True, and the pending question."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp1 = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    assert resp1.status_code == status.HTTP_201_CREATED
    data1 = resp1.json()

    resp2 = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.json()

    assert data2["attempt_id"] == data1["attempt_id"]
    assert data2["resumed"] is True
    assert data2["question_number"] == 1
    assert data2["question"]["question_id"] == data1["question"]["question_id"]

    # Verify only 1 QuizAttempt row exists
    attempts_count = (
        db_session.query(QuizAttempt)
        .filter(QuizAttempt.topic_id == sample_topic.id, QuizAttempt.mode == "adaptive")
        .count()
    )
    assert attempts_count == 1


def test_adaptive_wrong_question_id_gives_409(client, learner_token, sample_topic):
    """Submitting an answer for a question_id other than the active pending question yields 409."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    attempt_id = start_resp.json()["attempt_id"]
    active_qid = start_resp.json()["question"]["question_id"]

    wrong_qid = active_qid + 99999
    payload = {"question_id": wrong_qid, "selected_answer": "A"}
    resp = client.post(f"/api/quiz/adaptive/{attempt_id}/answer", json=payload, headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert "expected answer for question" in resp.json()["detail"].lower()


def test_adaptive_answering_same_question_twice_gives_409(client, learner_token, sample_topic):
    """Submitting an answer for an already answered question returns 409 Conflict."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    attempt_id = start_resp.json()["attempt_id"]
    q1_id = start_resp.json()["question"]["question_id"]

    # Step 1 answer
    ans_resp = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": q1_id, "selected_answer": "A"},
        headers=headers,
    )
    assert ans_resp.status_code == status.HTTP_200_OK
    assert ans_resp.json()["finished"] is False

    # Resubmit answer for q1_id
    resubmit_resp = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": q1_id, "selected_answer": "B"},
        headers=headers,
    )
    assert resubmit_resp.status_code == status.HTTP_409_CONFLICT


def test_adaptive_another_user_attempt_gives_404(
    client, learner_token, second_learner, sample_topic
):
    """Accessing or answering another user's quiz attempt returns 404 Not Found."""
    headers_user1 = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers_user1)
    attempt_id = start_resp.json()["attempt_id"]
    active_qid = start_resp.json()["question"]["question_id"]

    token_user2 = create_access_token(second_learner.id)
    headers_user2 = {"Authorization": f"Bearer {token_user2}"}

    resp = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": active_qid, "selected_answer": "A"},
        headers=headers_user2,
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_adaptive_unauthenticated_gives_401(client, sample_topic):
    """Unauthenticated calls to start or answer return 401 Unauthorized."""
    resp1 = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id})
    assert resp1.status_code == status.HTTP_401_UNAUTHORIZED

    resp2 = client.post("/api/quiz/adaptive/999/answer", json={"question_id": 1, "selected_answer": "A"})
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED


def test_adaptive_topic_with_fewer_than_8_questions_gives_409(
    client, learner_token, db_session
):
    """Starting an adaptive quiz for a topic with fewer than 8 questions returns 409 Conflict."""
    course = Course(title="Disposable Course For Adaptive Test", description="Testing topic validation")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    topic = Topic(title="Tiny Topic", description="Topic with insufficient questions", course_id=course.id)
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    # Add 5 questions
    for i in range(5):
        q = Question(
            topic_id=topic.id,
            question_text=f"Tiny question {i+1}?",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_answer="A",
            difficulty="Medium",
        )
        db_session.add(q)
    db_session.commit()

    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/adaptive/start", json={"topic_id": topic.id}, headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert "requires at least 8" in resp.json()["detail"].lower()


def test_adaptive_answer_reveals_correct_answer(client, learner_token, sample_topic):
    """Answering a question reveals correct_answer, correctness, and explanation while sanitizing next_question."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    attempt_id = start_resp.json()["attempt_id"]
    active_qid = start_resp.json()["question"]["question_id"]

    resp = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": active_qid, "selected_answer": "A"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["attempt_id"] == attempt_id
    assert data["question_id"] == active_qid
    assert "is_correct" in data
    assert isinstance(data["is_correct"], bool)
    assert data["correct_answer"] in ["A", "B", "C", "D"]
    assert data["explanation"] is not None
    assert data["finished"] is False
    assert data["result"] is None

    next_q = data["next_question"]
    assert next_q is not None
    assert "correct_answer" not in next_q
    assert "difficulty" not in next_q


def test_adaptive_complete_8_answers_workflow(
    client, learner_token, test_learner, sample_topic, db_session
):
    """Complete 8-step lifecycle: step progression, finalization, TopicMastery, history, and anti-resubmit."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    assert start_resp.status_code == status.HTTP_201_CREATED
    attempt_id = start_resp.json()["attempt_id"]
    curr_qid = start_resp.json()["question"]["question_id"]

    last_mastery_after = None

    # Complete 8 questions
    for step in range(1, 9):
        q_obj = db_session.query(Question).filter(Question.id == curr_qid).first()
        # Alternate correct and incorrect
        selected = q_obj.correct_answer if (step % 2 != 0) else ("B" if q_obj.correct_answer == "A" else "A")

        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": selected},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        data = ans_resp.json()

        step_row = (
            db_session.query(AdaptiveQuizStep)
            .filter(AdaptiveQuizStep.attempt_id == attempt_id, AdaptiveQuizStep.step_number == step)
            .first()
        )
        assert step_row is not None
        assert step_row.is_correct == (selected.upper() == q_obj.correct_answer.upper())
        assert step_row.mastery_after is not None
        last_mastery_after = float(step_row.mastery_after)

        if step < 8:
            assert data["finished"] is False
            assert data["next_question"] is not None
            assert data["result"] is None
            curr_qid = data["next_question"]["question_id"]
        else:
            assert data["finished"] is True
            assert data["next_question"] is None
            result = data["result"]
            assert result is not None
            assert result["attempt_id"] == attempt_id
            assert result["total_questions"] == 8
            assert result["score"] == 4  # 4 correct out of 8
            assert result["correct_answers"] == 4
            assert result["incorrect_answers"] == 4
            assert pytest.approx(result["mastery_after"], 0.0001) == last_mastery_after

    # Verify attempt completion state in DB
    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    assert attempt.status == "completed"
    assert attempt.completed_at is not None
    assert attempt.score == 4

    # Verify 8 QuizResponse rows saved
    resp_count = db_session.query(QuizResponse).filter(QuizResponse.attempt_id == attempt_id).count()
    assert resp_count == 8

    # Verify 8 AdaptiveQuizStep rows saved
    step_count = db_session.query(AdaptiveQuizStep).filter(AdaptiveQuizStep.attempt_id == attempt_id).count()
    assert step_count == 8

    # Verify TopicMastery updated
    tm = (
        db_session.query(TopicMastery)
        .filter(TopicMastery.user_id == test_learner.id, TopicMastery.topic_id == sample_topic.id)
        .first()
    )
    assert tm is not None
    assert tm.total_answers == 8
    assert pytest.approx(float(tm.mastery_probability), 0.0001) == last_mastery_after

    # Verify TopicMasteryHistory recorded
    history = (
        db_session.query(TopicMasteryHistory)
        .filter(TopicMasteryHistory.user_id == test_learner.id, TopicMasteryHistory.topic_id == sample_topic.id)
        .first()
    )
    assert history is not None
    assert history.attempt_id == attempt_id
    assert pytest.approx(float(history.mastery_after), 0.0001) == last_mastery_after

    # Follow-up answer call on completed attempt returns 409
    follow_up = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": curr_qid, "selected_answer": "A"},
        headers=headers,
    )
    assert follow_up.status_code == status.HTTP_409_CONFLICT


def test_adaptive_atomicity_on_8th_answer_failure(
    client, learner_token, test_learner, sample_topic, db_session, monkeypatch
):
    """If apply_attempt fails on the 8th answer, the transaction rolls back completely."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    attempt_id = start_resp.json()["attempt_id"]
    curr_qid = start_resp.json()["question"]["question_id"]

    # Answer steps 1..7 normally
    for step in range(1, 8):
        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": "A"},
            headers=headers,
        )
        assert ans_resp.status_code == status.HTTP_200_OK
        curr_qid = ans_resp.json()["next_question"]["question_id"]

    # Monkeypatch apply_attempt to simulate an unexpected error during 8th step finalization
    def _mock_failure(*args, **kwargs):
        raise RuntimeError("Simulated BKT failure during finalization")

    monkeypatch.setattr(adaptive_service_mod, "apply_attempt", _mock_failure)

    # 8th answer should trigger the failure and rollback
    with pytest.raises(RuntimeError, match="Simulated BKT failure"):
        client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_qid, "selected_answer": "A"},
            headers=headers,
        )

    # Verify rollback in DB:
    # 1. Attempt is still in_progress, completed_at is NULL
    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    assert attempt.status == "in_progress"
    assert attempt.completed_at is None
    assert attempt.score in (None, 0)

    # 2. Only 7 QuizResponse rows exist
    resp_count = db_session.query(QuizResponse).filter(QuizResponse.attempt_id == attempt_id).count()
    assert resp_count == 7

    # 3. Step 8 in AdaptiveQuizStep has not been marked answered
    step8 = (
        db_session.query(AdaptiveQuizStep)
        .filter(AdaptiveQuizStep.attempt_id == attempt_id, AdaptiveQuizStep.step_number == 8)
        .first()
    )
    assert step8 is not None
    assert step8.answered_at is None
    assert step8.selected_answer is None

    # 4. No TopicMastery or TopicMasteryHistory updated for this quiz
    tm = (
        db_session.query(TopicMastery)
        .filter(TopicMastery.user_id == test_learner.id, TopicMastery.topic_id == sample_topic.id)
        .first()
    )
    assert tm is None or tm.total_answers == 0

    history = (
        db_session.query(TopicMasteryHistory)
        .filter(TopicMasteryHistory.user_id == test_learner.id, TopicMasteryHistory.attempt_id == attempt_id)
        .first()
    )
    assert history is None


def test_backfill_ignores_abandoned_in_progress_adaptive_attempt(
    client, db_session, sample_topic
):
    """Backfill process must completely ignore in-progress adaptive quiz attempts."""
    # Create learner with an in-progress adaptive attempt
    user = User(
        name="Abandoned Learner",
        email="abandoned@learnwise.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Start adaptive quiz and answer 2 steps
    start_resp = client.post("/api/quiz/adaptive/start", json={"topic_id": sample_topic.id}, headers=headers)
    attempt_id = start_resp.json()["attempt_id"]
    q1 = start_resp.json()["question"]["question_id"]

    ans1 = client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": q1, "selected_answer": "A"},
        headers=headers,
    )
    q2 = ans1.json()["next_question"]["question_id"]
    client.post(
        f"/api/quiz/adaptive/{attempt_id}/answer",
        json={"question_id": q2, "selected_answer": "B"},
        headers=headers,
    )

    # Run backfill across all users
    stats = run_backfill(db_session, dry_run=False)
    assert stats["users_inspected"] == 0

    # Confirm no TopicMastery was created for this user
    tm = db_session.query(TopicMastery).filter(TopicMastery.user_id == user.id).first()
    assert tm is None
