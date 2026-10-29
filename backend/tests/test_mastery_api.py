from fastapi import status
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.question import Question
from app.models.topic import Topic
from app.models.user import User
from app.services.bkt import classify
from app.utils.jwt import create_access_token
from app.utils.security import hash_password


def test_mastery_endpoints_require_authentication(client):
    """Unauthenticated requests receive 401 Unauthorized on all three mastery endpoints."""
    # 1. /api/mastery/me
    resp_me = client.get("/api/mastery/me")
    assert resp_me.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. /api/mastery/me/courses/{course_id}
    resp_course = client.get("/api/mastery/me/courses/1")
    assert resp_course.status_code == status.HTTP_401_UNAUTHORIZED

    # 3. /api/mastery/me/topics/{topic_id}
    resp_topic = client.get("/api/mastery/me/topics/1")
    assert resp_topic.status_code == status.HTTP_401_UNAUTHORIZED


def test_fresh_learner_sees_all_topics_not_attempted_and_empty_summaries(client, learner_token, db_session):
    """A fresh learner sees all 24 topics as not_attempted, and course summaries have zero attempted counts."""
    headers = {"Authorization": f"Bearer {learner_token}"}

    # Verify /api/mastery/me
    resp = client.get("/api/mastery/me", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    all_topics = resp.json()

    # The 4 seeded baseline courses each have 6 topics -> total 24
    assert len(all_topics) == 24

    for item in all_topics:
        assert item["status"] == "not_attempted"
        assert item["mastery_probability"] is None
        assert item["total_answers"] == 0
        assert item["correct_answers"] == 0
        assert item["last_answered_at"] is None
        assert "course_id" in item
        assert "course_title" in item
        assert "topic_id" in item
        assert "topic_title" in item
        assert "order" in item

    # Verify /api/mastery/me/courses/{course_id} for each baseline course
    courses = db_session.query(Course).all()
    assert len(courses) == 4

    for course in courses:
        resp_c = client.get(f"/api/mastery/me/courses/{course.id}", headers=headers)
        assert resp_c.status_code == status.HTTP_200_OK
        data = resp_c.json()

        assert data["course_id"] == course.id
        assert data["course_title"] == course.title
        summary = data["summary"]
        assert summary["total_topics"] == len(data["topics"])
        assert summary["not_attempted"] == len(data["topics"])
        assert summary["weak"] == 0
        assert summary["developing"] == 0
        assert summary["strong"] == 0
        assert summary["average_mastery_attempted"] is None

        for t in data["topics"]:
            assert t["status"] == "not_attempted"
            assert t["mastery_probability"] is None
            assert t["total_answers"] == 0
            assert t["correct_answers"] == 0


def test_mastery_reflects_post_quiz_progression_while_others_stay_not_attempted(
    client, learner_token, db_session
):
    """Submitting a quiz updates attempted topics' status & probability, while other topics stay not_attempted."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    assert course is not None

    # Pick 2 questions under a single topic to submit
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    assert topic is not None
    questions = (
        db_session.query(Question)
        .filter(Question.topic_id == topic.id)
        .limit(2)
        .all()
    )
    assert len(questions) == 2

    submission_payload = {
        "course_id": course.id,
        "answers": [
            {"question_id": questions[0].id, "selected_answer": questions[0].correct_answer},
            {"question_id": questions[1].id, "selected_answer": questions[1].correct_answer},
        ],
    }

    submit_resp = client.post("/api/quiz/submit", json=submission_payload, headers=headers)
    assert submit_resp.status_code == status.HTTP_200_OK

    # Check /api/mastery/me
    resp_me = client.get("/api/mastery/me", headers=headers)
    assert resp_me.status_code == status.HTTP_200_OK
    items = resp_me.json()

    attempted_item = next(it for it in items if it["topic_id"] == topic.id)
    assert attempted_item["status"] in ("developing", "strong")
    assert attempted_item["mastery_probability"] is not None
    assert attempted_item["mastery_probability"] > 0.30
    assert attempted_item["total_answers"] == 2
    assert attempted_item["correct_answers"] == 2
    assert attempted_item["last_answered_at"] is not None

    # Verify all other topics across the database remain not_attempted
    for it in items:
        if it["topic_id"] != topic.id:
            assert it["status"] == "not_attempted"
            assert it["mastery_probability"] is None
            assert it["total_answers"] == 0
            assert it["correct_answers"] == 0

    # Check /api/mastery/me/courses/{course_id}
    resp_course = client.get(f"/api/mastery/me/courses/{course.id}", headers=headers)
    assert resp_course.status_code == status.HTTP_200_OK
    c_data = resp_course.json()
    summary = c_data["summary"]

    assert summary["not_attempted"] == len(c_data["topics"]) - 1
    assert summary["not_attempted"] + summary["weak"] + summary["developing"] + summary["strong"] == summary["total_topics"]
    assert summary["average_mastery_attempted"] is not None
    assert round(summary["average_mastery_attempted"], 4) == round(attempted_item["mastery_probability"], 4)


def test_mastery_endpoints_404_on_unknown_course_and_topic(client, learner_token):
    """404 Not Found is returned for non-existent course and topic IDs."""
    headers = {"Authorization": f"Bearer {learner_token}"}

    resp_course = client.get("/api/mastery/me/courses/999999", headers=headers)
    assert resp_course.status_code == status.HTTP_404_NOT_FOUND
    assert resp_course.json()["detail"] == "Course not found"

    resp_topic = client.get("/api/mastery/me/topics/999999", headers=headers)
    assert resp_topic.status_code == status.HTTP_404_NOT_FOUND
    assert resp_topic.json()["detail"] == "Topic not found"


def test_topic_history_endpoint_returns_entries_oldest_first_after_two_submissions(
    client, learner_token, db_session
):
    """Topic history endpoint returns entries in chronological oldest-first order after multiple submissions."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    questions = (
        db_session.query(Question)
        .filter(Question.topic_id == topic.id)
        .limit(2)
        .all()
    )

    # First submission: correct answer on question 0
    sub1 = {
        "course_id": course.id,
        "answers": [{"question_id": questions[0].id, "selected_answer": questions[0].correct_answer}],
    }
    resp1 = client.post("/api/quiz/submit", json=sub1, headers=headers)
    assert resp1.status_code == status.HTTP_200_OK
    attempt1_id = resp1.json()["attempt_id"]

    # Second submission: incorrect answer on question 1
    wrong_answer = "B" if questions[1].correct_answer != "B" else "C"
    sub2 = {
        "course_id": course.id,
        "answers": [{"question_id": questions[1].id, "selected_answer": wrong_answer}],
    }
    resp2 = client.post("/api/quiz/submit", json=sub2, headers=headers)
    assert resp2.status_code == status.HTTP_200_OK
    attempt2_id = resp2.json()["attempt_id"]

    # Query topic mastery detail
    detail_resp = client.get(f"/api/mastery/me/topics/{topic.id}", headers=headers)
    assert detail_resp.status_code == status.HTTP_200_OK
    data = detail_resp.json()

    assert data["topic_id"] == topic.id
    assert data["course_id"] == course.id
    assert data["total_answers"] == 2
    assert data["correct_answers"] == 1
    history = data["history"]
    assert len(history) == 2

    # Oldest first ordering assertions
    assert history[0]["attempt_id"] == attempt1_id
    assert history[1]["attempt_id"] == attempt2_id
    assert history[0]["created_at"] <= history[1]["created_at"]

    # Continuity assertions
    assert history[0]["mastery_before"] == 0.30
    assert history[0]["correct_in_attempt"] == 1
    assert history[0]["answers_in_attempt"] == 1
    assert round(history[0]["mastery_after"], 5) == round(history[1]["mastery_before"], 5)
    assert history[1]["correct_in_attempt"] == 0
    assert history[1]["answers_in_attempt"] == 1
    assert round(data["mastery_probability"], 5) == round(history[1]["mastery_after"], 5)


def test_one_learner_cannot_see_another_learners_mastery(client, learner_token, db_session):
    """Mastery and history data are strictly isolated per authenticated learner."""
    # Learner 1 (from fixture) submits a quiz
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    q = db_session.query(Question).filter(Question.topic_id == topic.id).first()

    headers_learner1 = {"Authorization": f"Bearer {learner_token}"}
    sub = {
        "course_id": course.id,
        "answers": [{"question_id": q.id, "selected_answer": q.correct_answer}],
    }
    resp1 = client.post("/api/quiz/submit", json=sub, headers=headers_learner1)
    assert resp1.status_code == status.HTTP_200_OK

    # Create Learner 2
    learner2 = User(
        name="Second Learner",
        email="second.learner@learnwise.com",
        password_hash=hash_password("Pass12345!"),
        role="learner",
    )
    db_session.add(learner2)
    db_session.commit()
    db_session.refresh(learner2)

    learner2_token = create_access_token(learner2.id)
    headers_learner2 = {"Authorization": f"Bearer {learner2_token}"}

    # Learner 2 calls /api/mastery/me
    resp_me_2 = client.get("/api/mastery/me", headers=headers_learner2)
    assert resp_me_2.status_code == status.HTTP_200_OK
    items_2 = resp_me_2.json()
    assert len(items_2) == 24
    for it in items_2:
        assert it["status"] == "not_attempted"
        assert it["mastery_probability"] is None
        assert it["total_answers"] == 0

    # Learner 2 calls /api/mastery/me/courses/{course.id}
    resp_course_2 = client.get(f"/api/mastery/me/courses/{course.id}", headers=headers_learner2)
    assert resp_course_2.status_code == status.HTTP_200_OK
    summary_2 = resp_course_2.json()["summary"]
    assert summary_2["not_attempted"] == len(resp_course_2.json()["topics"])
    assert summary_2["weak"] == 0
    assert summary_2["developing"] == 0
    assert summary_2["strong"] == 0
    assert summary_2["average_mastery_attempted"] is None

    # Learner 2 calls /api/mastery/me/topics/{topic.id}
    resp_topic_2 = client.get(f"/api/mastery/me/topics/{topic.id}", headers=headers_learner2)
    assert resp_topic_2.status_code == status.HTTP_200_OK
    t_data_2 = resp_topic_2.json()
    assert t_data_2["status"] == "not_attempted"
    assert t_data_2["mastery_probability"] is None
    assert t_data_2["total_answers"] == 0
    assert t_data_2["history"] == []
