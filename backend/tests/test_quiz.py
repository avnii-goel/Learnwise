from fastapi import status
from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt


def test_quiz_generate_count_no_answers_and_topic_coverage(client, learner_token, db_session):
    """Quiz generation returns 20 questions, omits correct_answer, and covers every topic."""
    # Use the first course (Computer Networks)
    course = db_session.query(Course).first()
    assert course is not None

    course_topics = db_session.query(Topic).filter(Topic.course_id == course.id).all()
    expected_topic_ids = {t.id for t in course_topics}
    assert len(expected_topic_ids) == 6

    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post(f"/api/quiz/generate/course/{course.id}", headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    assert data["course_id"] == course.id
    questions = data["questions"]

    # 1. Right count
    assert len(questions) == 20

    # 2. No correct_answer field in any question
    for q in questions:
        assert "correct_answer" not in q
        assert "question_id" in q
        assert "topic_id" in q
        assert "question_text" in q
        assert "option_a" in q
        assert "option_b" in q
        assert "option_c" in q
        assert "option_d" in q

    # 3. Covers every topic of the course
    generated_topic_ids = {q["topic_id"] for q in questions}
    assert expected_topic_ids.issubset(generated_topic_ids)


def test_quiz_submit_rejects_duplicate_questions(client, learner_token, db_session):
    """Quiz submission rejects duplicate question IDs with 400 Bad Request."""
    course = db_session.query(Course).first()
    question = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == course.id)
        .first()
    )
    assert question is not None

    headers = {"Authorization": f"Bearer {learner_token}"}
    duplicate_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": question.id, "selected_answer": "A"},
            {"question_id": question.id, "selected_answer": "B"},
        ],
    }

    resp = client.post("/api/quiz/submit", json=duplicate_payload, headers=headers)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "duplicate" in resp.json()["detail"].lower()


def test_quiz_submit_rejects_wrong_course_questions(client, learner_token, db_session):
    """Quiz submission rejects questions belonging to a different course with 400."""
    courses = db_session.query(Course).order_by(Course.id).all()
    assert len(courses) >= 2
    course_1 = courses[0]
    course_2 = courses[1]

    # Find a question belonging to course_2
    foreign_question = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == course_2.id)
        .first()
    )
    assert foreign_question is not None

    headers = {"Authorization": f"Bearer {learner_token}"}
    mismatched_payload = {
        "course_id": course_1.id,
        "answers": [
            {"question_id": foreign_question.id, "selected_answer": "A"},
        ],
    }

    resp = client.post("/api/quiz/submit", json=mismatched_payload, headers=headers)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "not belong to the selected course" in resp.json()["detail"].lower()


def test_quiz_scoring_and_user_linkage(client, test_learner, learner_token, db_session):
    """Quiz scoring correctly calculates points on a known answer set and links attempt to user."""
    course = db_session.query(Course).first()
    questions = (
        db_session.query(Question)
        .join(Topic, Question.topic_id == Topic.id)
        .filter(Topic.course_id == course.id)
        .limit(3)
        .all()
    )
    assert len(questions) == 3

    q1, q2, q3 = questions[0], questions[1], questions[2]

    # Deliberate wrong answer for q3
    wrong_for_q3 = "B" if q3.correct_answer.upper() == "A" else "A"

    submission_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": q1.id, "selected_answer": q1.correct_answer},  # Correct
            {"question_id": q2.id, "selected_answer": q2.correct_answer},  # Correct
            {"question_id": q3.id, "selected_answer": wrong_for_q3},        # Incorrect
        ],
    }

    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/quiz/submit", json=submission_payload, headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    assert data["score"] == 2
    assert data["total_questions"] == 3
    assert data["correct_answers"] == 2
    assert data["incorrect_answers"] == 1
    assert data["percentage"] == 66.67

    attempt_id = data["attempt_id"]

    # Verify attempt is linked to the logged-in user in database
    attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    assert attempt is not None
    assert attempt.user_id == test_learner.id
    assert attempt.user.email == test_learner.email
    assert attempt.course_id == course.id
    assert attempt.course.title == course.title
    assert attempt in test_learner.quiz_attempts
