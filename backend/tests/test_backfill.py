import pytest
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.seeds.backfill_mastery import run_backfill


def test_user_with_only_pre_mastery_attempts_equals_live_flow_result(
    client, learner_token, test_learner, db_session
):
    """(a) A user with only pre-mastery attempts gets backfilled and equals the live-flow result."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    questions = (
        db_session.query(Question)
        .filter(Question.topic_id == topic.id)
        .limit(2)
        .all()
    )

    # 1. Submit quiz via live endpoint
    sub = {
        "course_id": course.id,
        "answers": [
            {"question_id": questions[0].id, "selected_answer": questions[0].correct_answer},
            {"question_id": questions[1].id, "selected_answer": questions[1].correct_answer},
        ],
    }
    resp = client.post("/api/quiz/submit", json=sub, headers=headers)
    assert resp.status_code == 200

    # Capture ground-truth live-flow values
    live_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    live_prob = live_mastery.mastery_probability
    live_total = live_mastery.total_answers
    live_correct = live_mastery.correct_answers

    live_history = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    live_h_before = live_history.mastery_before
    live_h_after = live_history.mastery_after
    live_h_ans = live_history.answers_in_attempt
    live_h_corr = live_history.correct_in_attempt

    # 2. Simulate pre-mastery era by deleting mastery & history rows while keeping attempts & responses
    db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).delete()
    db_session.query(TopicMastery).filter_by(user_id=test_learner.id).delete()
    db_session.commit()

    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 0

    # 3. Run historical backfill
    stats = run_backfill(db_session, dry_run=False)
    assert stats["users_backfilled"] == 1
    assert stats["attempts_replayed"] == 1

    # 4. Assert backfill result equals live flow result
    bf_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    assert round(bf_mastery.mastery_probability, 6) == round(live_prob, 6)
    assert bf_mastery.total_answers == live_total
    assert bf_mastery.correct_answers == live_correct

    bf_history = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    assert round(bf_history.mastery_before, 6) == round(live_h_before, 6)
    assert round(bf_history.mastery_after, 6) == round(live_h_after, 6)
    assert bf_history.answers_in_attempt == live_h_ans
    assert bf_history.correct_in_attempt == live_h_corr


def test_user_who_already_has_history_is_skipped(
    client, learner_token, test_learner, db_session, capsys
):
    """(b) A user who already has history is skipped and their rows are unchanged."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    q = db_session.query(Question).first()

    # Submit attempt 1 via live flow
    client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": q.id, "selected_answer": q.correct_answer}]},
        headers=headers,
    )

    initial_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id)
        .all()
    )
    initial_history = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id)
        .all()
    )
    initial_probs = [m.mastery_probability for m in initial_mastery]
    initial_h_ids = [h.id for h in initial_history]

    # Run backfill without --rebuild-user
    stats = run_backfill(db_session, dry_run=False)

    assert stats["users_skipped"] == 1
    assert stats["users_backfilled"] == 0
    assert stats["attempts_replayed"] == 0

    # Verify rows are completely unchanged
    current_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id)
        .all()
    )
    current_history = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id)
        .all()
    )
    assert [m.mastery_probability for m in current_mastery] == initial_probs
    assert [h.id for h in current_history] == initial_h_ids

    # Verify warning message was printed
    captured = capsys.readouterr()
    assert f"WARNING: Skipping user {test_learner.id}" in captured.out


def test_rebuild_user_produces_clean_in_order_replay(
    client, learner_token, test_learner, db_session
):
    """(c) --rebuild-user on a user with mixed attempts produces exactly what a clean in-order replay would."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    questions = (
        db_session.query(Question)
        .filter(Question.topic_id == topic.id)
        .limit(2)
        .all()
    )

    # Submit 2 attempts
    client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": questions[0].id, "selected_answer": questions[0].correct_answer}]},
        headers=headers,
    )
    wrong_ans = "B" if questions[1].correct_answer != "B" else "C"
    client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": questions[1].id, "selected_answer": wrong_ans}]},
        headers=headers,
    )

    expected_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    expected_prob = expected_mastery.mastery_probability

    # Corrupt the user's mastery row intentionally to simulate corrupt/mixed state
    expected_mastery.mastery_probability = 0.999
    expected_mastery.total_answers = 999
    db_session.commit()

    # Run backfill with --rebuild-user
    stats = run_backfill(db_session, dry_run=False, rebuild_user_id=test_learner.id)
    assert stats["users_backfilled"] == 1
    assert stats["attempts_replayed"] == 2
    assert stats["deleted_mastery_rows"] >= 1
    assert stats["deleted_history_rows"] == 2

    # Assert mastery probability is restored to exact in-order calculation
    rebuilt_mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    assert round(rebuilt_mastery.mastery_probability, 6) == round(expected_prob, 6)
    assert rebuilt_mastery.total_answers == 2
    assert rebuilt_mastery.correct_answers == 1


def test_running_backfill_twice_changes_nothing(
    client, learner_token, test_learner, db_session
):
    """(d) Running the backfill twice changes nothing."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    q = db_session.query(Question).first()

    # Submit quiz and remove mastery rows
    client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": q.id, "selected_answer": q.correct_answer}]},
        headers=headers,
    )
    db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).delete()
    db_session.query(TopicMastery).filter_by(user_id=test_learner.id).delete()
    db_session.commit()

    # First run backfills
    stats1 = run_backfill(db_session, dry_run=False)
    assert stats1["users_backfilled"] == 1
    first_mastery = db_session.query(TopicMastery).filter_by(user_id=test_learner.id).one()
    first_prob = first_mastery.mastery_probability
    first_history_count = db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count()

    # Second run skips and changes nothing
    stats2 = run_backfill(db_session, dry_run=False)
    assert stats2["users_backfilled"] == 0
    assert stats2["users_skipped"] == 1
    assert stats2["attempts_replayed"] == 0

    second_mastery = db_session.query(TopicMastery).filter_by(user_id=test_learner.id).one()
    assert second_mastery.mastery_probability == first_prob
    second_history_count = db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count()
    assert second_history_count == first_history_count


def test_dry_run_writes_nothing(
    client, learner_token, test_learner, db_session
):
    """(e) --dry-run writes nothing to the database, even when replaying or rebuilding."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    q = db_session.query(Question).first()

    # Submit quiz and remove mastery rows
    client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": q.id, "selected_answer": q.correct_answer}]},
        headers=headers,
    )
    db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).delete()
    db_session.query(TopicMastery).filter_by(user_id=test_learner.id).delete()
    db_session.commit()

    # Standard dry run
    stats = run_backfill(db_session, dry_run=True)
    assert stats["dry_run"] is True
    assert stats["attempts_replayed"] == 1

    # Verify zero rows written
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 0
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 0

    # Dry run with --rebuild-user after real write
    run_backfill(db_session, dry_run=False)
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 1
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 1

    # Dry run rebuild
    rebuild_dry_stats = run_backfill(db_session, dry_run=True, rebuild_user_id=test_learner.id)
    assert rebuild_dry_stats["dry_run"] is True
    assert rebuild_dry_stats["deleted_mastery_rows"] == 1
    assert rebuild_dry_stats["deleted_history_rows"] == 1

    # Verify rows were NOT deleted
    assert db_session.query(TopicMastery).filter_by(user_id=test_learner.id).count() == 1
    assert db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).count() == 1


def test_backfill_timestamps_use_attempt_completed_at(
    client, learner_token, test_learner, db_session
):
    """(a) History created_at equals attempt completed_at; (b) mastery last_answered_at equals latest attempt completed_at."""
    from datetime import datetime, timezone, timedelta

    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    topic = db_session.query(Topic).filter(Topic.course_id == course.id).first()
    questions = (
        db_session.query(Question)
        .filter(Question.topic_id == topic.id)
        .limit(2)
        .all()
    )

    t1 = datetime(2025, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 20, 15, 30, 0, tzinfo=timezone.utc)

    # Submit 2 attempts
    r1 = client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": questions[0].id, "selected_answer": questions[0].correct_answer}]},
        headers=headers,
    )
    attempt1_id = r1.json()["attempt_id"]

    r2 = client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": questions[1].id, "selected_answer": questions[1].correct_answer}]},
        headers=headers,
    )
    attempt2_id = r2.json()["attempt_id"]

    # Explicitly set historical completed_at timestamps on the attempts
    att1 = db_session.query(QuizAttempt).filter_by(id=attempt1_id).one()
    att1.started_at = t1 - timedelta(minutes=10)
    att1.completed_at = t1

    att2 = db_session.query(QuizAttempt).filter_by(id=attempt2_id).one()
    att2.started_at = t2 - timedelta(minutes=10)
    att2.completed_at = t2

    # Delete mastery & history to simulate pre-mastery era
    db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id).delete()
    db_session.query(TopicMastery).filter_by(user_id=test_learner.id).delete()
    db_session.commit()

    # Run backfill
    run_backfill(db_session, dry_run=False)

    # (a) Assert each history row's created_at equals its attempt's completed_at
    h1 = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, attempt_id=attempt1_id)
        .one()
    )
    h2 = (
        db_session.query(TopicMasteryHistory)
        .filter_by(user_id=test_learner.id, attempt_id=attempt2_id)
        .one()
    )
    assert h1.created_at == t1
    assert h2.created_at == t2

    # (b) Assert last_answered_at on the mastery row equals the latest replayed attempt's completed_at
    mastery = (
        db_session.query(TopicMastery)
        .filter_by(user_id=test_learner.id, topic_id=topic.id)
        .one()
    )
    assert mastery.last_answered_at == t2


def test_live_submit_flow_timestamps_use_current_time(
    client, learner_token, test_learner, db_session
):
    """(c) The live submit flow behavior is unchanged and uses the current time."""
    from datetime import datetime, timezone, timedelta

    headers = {"Authorization": f"Bearer {learner_token}"}
    course = db_session.query(Course).first()
    q = db_session.query(Question).first()

    before = datetime.now(timezone.utc) - timedelta(seconds=2)
    resp = client.post(
        "/api/quiz/submit",
        json={"course_id": course.id, "answers": [{"question_id": q.id, "selected_answer": q.correct_answer}]},
        headers=headers,
    )
    assert resp.status_code == 200
    after = datetime.now(timezone.utc) + timedelta(seconds=2)

    mastery = db_session.query(TopicMastery).filter_by(user_id=test_learner.id, topic_id=q.topic_id).one()
    history = db_session.query(TopicMasteryHistory).filter_by(user_id=test_learner.id, topic_id=q.topic_id).one()

    # Live flow timestamps fall within current execution window
    assert before <= mastery.last_answered_at <= after
    assert before <= history.created_at <= after

