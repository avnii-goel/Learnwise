"""Tests for the Phase 8 verification script (scripts/verify_phase8.py).

Verifies:
T1: verify script passes without FAIL on consistent data (worked example dataset).
T2: verify script detects mismatches when a dashboard service output is corrupted.
T3: verify script is strictly read-only (row counts unchanged, no commit/insert/update/delete in script source).
"""

import os
import sys
from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure repo root is on sys.path so scripts.verify_phase8 can be imported
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from scripts.verify_phase8 import run_checks
from app.models.course import Course
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.quiz_attempt import QuizAttempt
from app.models.user import User
from app.utils.security import hash_password


@pytest.fixture
def consistent_phase8_data(db_session: Session):
    """Builds a small, strictly consistent dataset including the worked example."""
    course = Course(
        title="Verification Test Course",
        description="Course for verify script testing",
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    topic = Topic(
        title="Verification Topic 1",
        description="Worked example topic",
        course_id=course.id,
        order=1,
    )
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)

    now = datetime.now(timezone.utc)

    # 3 learners matching worked example
    # Learner A: mastery 0.85, 4 correct of 4
    # Learner B: mastery 0.6460, 1 correct of 1
    # Learner C: mastery 0.1486, 0 correct of 1
    learners_data = [
        ("Learner A", "learnerA@example.com", 0.8500, 4, 4),
        ("Learner B", "learnerB@example.com", 0.6460, 1, 1),
        ("Learner C", "learnerC@example.com", 0.1486, 0, 1),
    ]

    learners = []
    for name, email, mastery, correct, total in learners_data:
        u = User(
            name=name,
            email=email,
            password_hash=hash_password("Pass123!"),
            role="learner",
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        learners.append(u)

        tm = TopicMastery(
            user_id=u.id,
            topic_id=topic.id,
            mastery_probability=mastery,
            total_answers=total,
            correct_answers=correct,
            last_answered_at=now,
        )
        db_session.add(tm)

    # Add completed quiz attempts: 6/8, 14/20, 3/8
    attempts_data = [
        (learners[0].id, 6, 8, "adaptive"),
        (learners[1].id, 14, 20, "fixed"),
        (learners[2].id, 3, 8, "adaptive"),
    ]

    for uid, score, total_q, mode in attempts_data:
        qa = QuizAttempt(
            user_id=uid,
            course_id=course.id,
            topic_id=topic.id if mode == "adaptive" else None,
            mode=mode,
            score=score,
            total_questions=total_q,
            status="completed",
            started_at=now,
            completed_at=now,
        )
        db_session.add(qa)

    db_session.commit()
    return course, topic, learners


def test_verify_script_passes_on_consistent_data(db_session: Session, consistent_phase8_data):
    """T1: run_checks returns no FAIL (WARN is permitted; V8 is skipped when synthetic users are absent)."""
    results = run_checks(db_session)
    assert len(results) >= 8

    failures = [r for r in results if r[1] == "FAIL"]
    assert not failures, f"Expected 0 FAILs on consistent data, got: {failures}"

    # Verify each check was executed
    check_names = [r[0] for r in results]
    assert any("V1" in name for name in check_names)
    assert any("V2" in name for name in check_names)
    assert any("V3" in name for name in check_names)
    assert any("V4" in name for name in check_names)
    assert any("V5" in name for name in check_names)
    assert any("V6" in name for name in check_names)


def test_verify_script_detects_mismatch(db_session: Session, consistent_phase8_data, monkeypatch):
    """T2: monkeypatch a service to return wrong metrics; verify run_checks reports at least one FAIL."""
    import scripts.verify_phase8 as verify_mod
    original_get_topics = verify_mod.get_instructor_topics

    def corrupted_get_topics(db):
        resp = original_get_topics(db)
        if resp.topics:
            # Corrupt the first topic's avg_mastery
            resp.topics[0].avg_mastery = 0.9999
        return resp

    monkeypatch.setattr(verify_mod, "get_instructor_topics", corrupted_get_topics)

    results = run_checks(db_session)
    failures = [r for r in results if r[1] == "FAIL"]
    assert len(failures) >= 1

    failed_names = [f[0] for f in failures]
    assert any("V3" in name for name in failed_names)


def test_verify_script_is_read_only(db_session: Session, consistent_phase8_data):
    """T3: Row counts are identical before and after run_checks; script source contains no commit/mutations."""
    # Count rows before
    tables = [User, Course, Topic, TopicMastery, QuizAttempt]
    counts_before = {tbl.__tablename__: db_session.query(tbl).count() for tbl in tables}

    run_checks(db_session)

    # Count rows after
    counts_after = {tbl.__tablename__: db_session.query(tbl).count() for tbl in tables}
    assert counts_before == counts_after, f"Row count changed: before={counts_before}, after={counts_after}"

    # Verify script file source code
    script_path = os.path.join(repo_root, "scripts", "verify_phase8.py")
    with open(script_path, "r") as f:
        code = f.read()

    assert "commit(" not in code, "Verification script must not contain commit("
    assert "INSERT" not in code.upper(), "Verification script must not contain INSERT"
    assert "UPDATE" not in code.upper(), "Verification script must not contain UPDATE"
    assert "DELETE" not in code.upper(), "Verification script must not contain DELETE"
