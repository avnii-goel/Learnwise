from fastapi import status


def test_unauthenticated_requests_blocked(client):
    """Unauthenticated access to courses is blocked."""
    r = client.get("/api/courses/")
    assert r.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_learner_can_read_courses(client, learner_token):
    """Logged in learners can read courses and their topics."""
    headers = {"Authorization": f"Bearer {learner_token}"}

    r_courses = client.get("/api/courses/", headers=headers)
    assert r_courses.status_code == status.HTTP_200_OK
    courses = r_courses.json()
    assert len(courses) >= 4

    course_id = courses[0]["id"]
    r_topics = client.get(f"/api/courses/{course_id}/topics/", headers=headers)
    assert r_topics.status_code == status.HTTP_200_OK
    topics = r_topics.json()
    assert len(topics) == 6


def test_learner_cannot_create_course_returns_403(client, learner_token):
    """Learners do not have permission to create courses (403 Forbidden)."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    payload = {
        "title": "Unauthorized Advanced AI",
        "description": "Should not be created by learner",
    }
    r = client.post("/api/courses/", json=payload, headers=headers)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_instructor_can_create_course_topic_and_resource(client, instructor_token):
    """Instructors can create courses, topics, and resources."""
    headers = {"Authorization": f"Bearer {instructor_token}"}

    # 1. Create Course
    course_payload = {
        "title": "Machine Learning Foundations",
        "description": "Introduction to supervised and unsupervised learning.",
    }
    r_course = client.post("/api/courses/", json=course_payload, headers=headers)
    assert r_course.status_code == status.HTTP_200_OK
    course_data = r_course.json()
    course_id = course_data["id"]
    assert course_data["title"] == course_payload["title"]

    # 2. Create Topic under new course
    topic_payload = {
        "title": "Linear Regression",
        "description": "Ordinary Least Squares and gradient descent.",
        "order": 1,
    }
    r_topic = client.post(f"/api/courses/{course_id}/topics/", json=topic_payload, headers=headers)
    assert r_topic.status_code == status.HTTP_200_OK
    topic_data = r_topic.json()
    topic_id = topic_data["id"]
    assert topic_data["title"] == topic_payload["title"]

    # 3. Create Learning Resource under topic
    resource_payload = {
        "title": "Gradient Descent Video Lecture",
        "description": "Detailed derivation of gradient descent optimization.",
        "resource_type": "video",
        "url": "https://example.com/ml/gradient-descent",
        "order": 1,
    }
    r_resource = client.post(
        f"/api/courses/{course_id}/topics/{topic_id}/resources/",
        json=resource_payload,
        headers=headers
    )
    assert r_resource.status_code == status.HTTP_200_OK
    resource_data = r_resource.json()
    assert resource_data["title"] == resource_payload["title"]
    assert resource_data["resource_type"] == "video"
