
"""API-level end-to-end flow test for Phase 8.

Verifies:
1. Registration (field `name`), login, /me returns role "learner".
2. Adaptive quiz start idempotency (201 created, 200 resumed with identical attempt and question).
3. Complete 8-question adaptive attempt progression.
4. Consistency across mastery, dashboard overview, history, and trends.
5. In-progress abandoned attempt on a second topic is excluded from history, trends, and completed count.
6. Recommendations endpoint schema and impression click audit.
7. Instructor cohort metrics, reach counts, and authorization guards (403 for learner, 401 unauthenticated).
"""

import pytest
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.question import Question
from app.models.topic import Topic


@pytest.fixture
def ample_topic_and_second_topic(db_session: Session) -> tuple[Topic, Topic]:
    """Creates a primary topic with 24 questions and a secondary topic with 8 questions."""
    course = Course(
        title="Phase 8 E2E Course",
        description="Course providing topics for end-to-end verification",
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    topic1 = Topic(
        title="Primary E2E Topic",
        description="Topic containing 24 questions for full adaptive run",
        course_id=course.id,
        order=1,
    )
    topic2 = Topic(
        title="Secondary Abandoned Topic",
        description="Topic containing 8 questions for abandoned attempt test",
        course_id=course.id,
        order=2,
    )
    db_session.add_all([topic1, topic2])
    db_session.commit()
    db_session.refresh(topic1)
    db_session.refresh(topic2)

    # 24 questions for topic 1
    for diff in ["Easy", "Medium", "Hard"]:
        for i in range(1, 9):
            q = Question(
                topic_id=topic1.id,
                question_text=f"Topic 1 {diff} Question {i}",
                option_a="Option A",
                option_b="Option B",
                option_c="Option C",
                option_d="Option D",
                correct_answer="A",
                difficulty=diff,
            )
            db_session.add(q)

    # 8 questions for topic 2
    for i in range(1, 9):
        q = Question(
            topic_id=topic2.id,
            question_text=f"Topic 2 Question {i}",
            option_a="Option A",
            option_b="Option B",
            option_c="Option C",
            option_d="Option D",
            correct_answer="A",
            difficulty="Easy",
        )
        db_session.add(q)

    db_session.commit()
    return topic1, topic2


def test_phase8_complete_e2e_flow(client, db_session, instructor_token, ample_topic_and_second_topic):
    topic1, topic2 = ample_topic_and_second_topic

    # 1. Register, login, verify GET /api/auth/me returns role "learner"
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": "phase8.learner@example.com",
            "password": "Password123!",
            "name": "Phase 8 Learner",
        },
    )
    assert reg_resp.status_code == 201
    assert reg_resp.json()["name"] == "Phase 8 Learner"

    login_resp = client.post(
        "/api/auth/login",
        json={
            "email": "phase8.learner@example.com",
            "password": "Password123!",
        },
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    learner_headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/auth/me", headers=learner_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "learner"

    # 2. POST /api/quiz/adaptive/start: 201 initially, 200 on retry (idempotent resume)
    start_1 = client.post(
        "/api/quiz/adaptive/start",
        json={"topic_id": topic1.id},
        headers=learner_headers,
    )
    assert start_1.status_code == 201
    attempt_id = start_1.json()["attempt_id"]
    first_q_id = start_1.json()["question"]["question_id"]

    start_2 = client.post(
        "/api/quiz/adaptive/start",
        json={"topic_id": topic1.id},
        headers=learner_headers,
    )
    assert start_2.status_code == 200
    assert start_2.json()["attempt_id"] == attempt_id
    assert start_2.json()["question"]["question_id"] == first_q_id
    assert start_2.json()["resumed"] is True

    # 3. Answer all 8 questions following next_question
    curr_q_id = first_q_id
    final_result = None

    for step in range(8):
        ans_resp = client.post(
            f"/api/quiz/adaptive/{attempt_id}/answer",
            json={"question_id": curr_q_id, "selected_answer": "A"},
            headers=learner_headers,
        )
        assert ans_resp.status_code == 200
        payload = ans_resp.json()

        if step < 7:
            assert payload["finished"] is False
            assert payload["next_question"] is not None
            curr_q_id = payload["next_question"]["question_id"]
        else:
            assert payload["finished"] is True
            final_result = payload["result"]
            assert final_result is not None

    score = final_result["score"]
    mastery_after = final_result["mastery_after"]

    # 4. Consistency across mastery, dashboard overview, history, and trends
    # 4a: GET /api/mastery/me
    m_resp = client.get("/api/mastery/me", headers=learner_headers)
    assert m_resp.status_code == 200
    topic1_m = next(t for t in m_resp.json() if t["topic_id"] == topic1.id)
    assert topic1_m["mastery_probability"] == mastery_after

    # 4b: GET /api/dashboard/me
    dash_resp = client.get("/api/dashboard/me", headers=learner_headers)
    assert dash_resp.status_code == 200
    ov = dash_resp.json()["overview"]
    assert ov["attempted_topics"] == 1
    assert ov["completed_quizzes"] == 1
    assert ov["avg_mastery_attempted"] == round(mastery_after, 4)

    # 4c: GET /api/dashboard/me/history
    hist_resp = client.get("/api/dashboard/me/history", headers=learner_headers)
    assert hist_resp.status_code == 200
    h_items = hist_resp.json()["items"]
    assert len(h_items) == 1
    assert h_items[0]["mode"] == "adaptive"
    assert h_items[0]["score"] == score
    assert h_items[0]["percentage"] == round(score / 8 * 100.0, 1)

    # 4d: GET /api/dashboard/me/trends
    trends_resp = client.get("/api/dashboard/me/trends", headers=learner_headers)
    assert trends_resp.status_code == 200
    assert len(trends_resp.json()["quiz_scores"]) == 1
    assert len(trends_resp.json()["mastery_progress"]) == 1
    assert trends_resp.json()["mastery_progress"][0]["avg_mastery"] == round(mastery_after, 4)

    # 5. Abandoned attempt: start on DIFFERENT topic, answer nothing; verify exclusion
    start_abandoned = client.post(
        "/api/quiz/adaptive/start",
        json={"topic_id": topic2.id},
        headers=learner_headers,
    )
    assert start_abandoned.status_code == 201

    # Verify history, trends, and overview completed count are unchanged
    hist_after = client.get("/api/dashboard/me/history", headers=learner_headers).json()["items"]
    assert len(hist_after) == 1

    trends_after = client.get("/api/dashboard/me/trends", headers=learner_headers).json()
    assert len(trends_after["quiz_scores"]) == 1
    assert len(trends_after["mastery_progress"]) == 1

    dash_after = client.get("/api/dashboard/me", headers=learner_headers).json()["overview"]
    assert dash_after["completed_quizzes"] == 1

    # 6. POST /api/recommendations/me
    rec_resp = client.post("/api/recommendations/me", headers=learner_headers)
    assert rec_resp.status_code == 200
    rec_json = rec_resp.json()
    assert "request_id" in rec_json
    assert "items" in rec_json

    if rec_json["items"]:
        first_imp = rec_json["items"][0]
        imp_id = first_imp["impression_id"]
        click_resp = client.post(
            f"/api/recommendations/impressions/{imp_id}/click",
            headers=learner_headers,
        )
        assert click_resp.status_code == 200
        assert click_resp.json()["clicked_at"] is not None

    # 7. Instructor view and authorization guards
    inst_headers = {"Authorization": f"Bearer {instructor_token}"}

    # 7a: Instructor Overview
    inst_ov = client.get("/api/dashboard/instructor/overview", headers=inst_headers)
    assert inst_ov.status_code == 200
    assert inst_ov.json()["total_learners"] >= 1
    assert inst_ov.json()["active_learners"] == 1

    # 7b: Instructor Learners
    inst_learners = client.get("/api/dashboard/instructor/learners", headers=inst_headers)
    assert inst_learners.status_code == 200
    learner_row = next(
        l for l in inst_learners.json()["items"] if l["email"] == "phase8.learner@example.com"
    )
    assert learner_row["attempted_topics"] == 1
    assert learner_row["completed_attempts"] == 1

    # 7c: Instructor Topics
    inst_topics = client.get("/api/dashboard/instructor/topics", headers=inst_headers)
    assert inst_topics.status_code == 200
    topic_row = next(t for t in inst_topics.json()["topics"] if t["topic_id"] == topic1.id)
    assert topic_row["learners_attempted"] == 1
    assert topic_row["avg_mastery"] == round(mastery_after, 4)

    # 7d: Authorization guards (403 for learner, 401 unauthenticated)
    for endpoint in [
        "/api/dashboard/instructor/overview",
        "/api/dashboard/instructor/learners",
        "/api/dashboard/instructor/topics",
    ]:
        assert client.get(endpoint, headers=learner_headers).status_code == 403
        assert client.get(endpoint).status_code == 401
