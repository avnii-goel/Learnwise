import pytest
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.quiz_attempt import QuizAttempt
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.seeds.seed_synthetic_learners import (
    seed_synthetic_learners,
    reset_synthetic_learners,
    REQUIRED_COURSE_TITLES,
)


@pytest.fixture(autouse=True)
def clean_synthetic_users(db_session: Session):
    """Ensures test database is cleared of synthetic users before and after each test."""
    db_session.query(User).filter(User.email.like("%@synthetic.learnwise.test")).delete()
    db_session.commit()
    yield
    db_session.query(User).filter(User.email.like("%@synthetic.learnwise.test")).delete()
    db_session.commit()


def test_dry_run_writes_nothing(db_session: Session):
    """--dry-run simulates execution without writing any users, attempts, or mastery rows."""
    stats = seed_synthetic_learners(db_session, num_learners=10, dry_run=True)
    assert stats["dry_run"] is True
    assert stats["learners_created"] == 10

    # Verify zero synthetic users or mastery rows persisted
    synthetic_count = (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .count()
    )
    assert synthetic_count == 0
    assert db_session.query(TopicMastery).count() == 0
    assert db_session.query(TopicMasteryHistory).count() == 0


def test_idempotent_second_run_creates_nothing(db_session: Session):
    """Running synthetic seeding twice skips existing learners and creates zero new rows."""
    stats1 = seed_synthetic_learners(db_session, num_learners=10, dry_run=False)
    assert stats1["learners_created"] == 10
    assert stats1["learners_skipped"] == 0

    user_count = (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .count()
    )
    assert user_count == 10
    attempts_count1 = db_session.query(QuizAttempt).count()

    # Second run should skip all 10 learners
    stats2 = seed_synthetic_learners(db_session, num_learners=10, dry_run=False)
    assert stats2["learners_created"] == 0
    assert stats2["learners_skipped"] == 10
    assert stats2["attempts_created"] == 0

    assert (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .count()
        == 10
    )
    assert db_session.query(QuizAttempt).count() == attempts_count1


def test_history_created_at_matches_attempt_completed_at_and_chronological(db_session: Session):
    """Each TopicMasteryHistory.created_at matches its QuizAttempt.completed_at in chronological order."""
    seed_synthetic_learners(db_session, num_learners=10, dry_run=False)

    users = (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .all()
    )
    assert len(users) == 10

    for user in users:
        # Check attempt <-> history timestamp consistency
        histories = (
            db_session.query(TopicMasteryHistory)
            .filter(TopicMasteryHistory.user_id == user.id)
            .all()
        )
        assert len(histories) > 0

        for h in histories:
            attempt = db_session.query(QuizAttempt).filter(QuizAttempt.id == h.attempt_id).one()
            assert h.created_at == attempt.completed_at

        # Check chronological ordering per topic
        topic_ids = {h.topic_id for h in histories}
        for t_id in topic_ids:
            t_histories = (
                db_session.query(TopicMasteryHistory)
                .filter(TopicMasteryHistory.user_id == user.id, TopicMasteryHistory.topic_id == t_id)
                .order_by(TopicMasteryHistory.created_at.asc(), TopicMasteryHistory.id.asc())
                .all()
            )
            for idx in range(len(t_histories) - 1):
                assert t_histories[idx].created_at <= t_histories[idx + 1].created_at
                assert round(t_histories[idx].mastery_after, 5) == round(t_histories[idx + 1].mastery_before, 5)


def test_mastery_rows_equal_clean_in_order_recomputation(db_session: Session):
    """Persisted TopicMastery rows match the latest TopicMasteryHistory progression record."""
    seed_synthetic_learners(db_session, num_learners=10, dry_run=False)

    user = (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .first()
    )
    assert user is not None

    masteries = (
        db_session.query(TopicMastery)
        .filter(TopicMastery.user_id == user.id)
        .all()
    )
    assert len(masteries) == 24  # 4 courses * 6 topics = 24 topics

    for m in masteries:
        latest_history = (
            db_session.query(TopicMasteryHistory)
            .filter(TopicMasteryHistory.user_id == user.id, TopicMasteryHistory.topic_id == m.topic_id)
            .order_by(TopicMasteryHistory.created_at.desc(), TopicMasteryHistory.id.desc())
            .first()
        )
        assert latest_history is not None
        assert round(m.mastery_probability, 6) == round(latest_history.mastery_after, 6)
        assert m.last_answered_at == latest_history.created_at


def test_group_a_mastery_higher_than_group_b(db_session: Session):
    """Group A (learner 1) shows higher average mastery than Group B (learner 2)."""
    seed_synthetic_learners(db_session, num_learners=5, dry_run=False)

    # In a 5-learner population:
    # Learner 1: Group A
    # Learner 2: Group B
    user_a = db_session.query(User).filter_by(email="synthetic-01@synthetic.learnwise.test").one()
    user_b = db_session.query(User).filter_by(email="synthetic-02@synthetic.learnwise.test").one()

    mastery_a = [
        m.mastery_probability
        for m in db_session.query(TopicMastery).filter_by(user_id=user_a.id).all()
    ]
    mastery_b = [
        m.mastery_probability
        for m in db_session.query(TopicMastery).filter_by(user_id=user_b.id).all()
    ]

    avg_a = sum(mastery_a) / len(mastery_a)
    avg_b = sum(mastery_b) / len(mastery_b)

    assert avg_a > avg_b
    assert avg_a > 0.90


def test_group_c_vs_group_d_course_contrast(db_session: Session):
    """Group C is stronger on Networks/OS than Group D; Group D is stronger on OOPS/SQL than Group C."""
    seed_synthetic_learners(db_session, num_learners=5, dry_run=False)

    # In a 5-learner population:
    # Learner 3: Group C (Networks/OS strong, OOPS/SQL weak)
    # Learner 4: Group D (OOPS/SQL strong, Networks/OS weak)
    user_c = db_session.query(User).filter_by(email="synthetic-03@synthetic.learnwise.test").one()
    user_d = db_session.query(User).filter_by(email="synthetic-04@synthetic.learnwise.test").one()

    courses = {c.title: c for c in db_session.query(Course).all()}
    net_os_ids = [courses["Computer Networks"].id, courses["Operating Systems"].id]
    oops_sql_ids = [courses["OOPS"].id, courses["SQL/DBMS"].id]

    def get_avg_mastery(user, course_ids):
        probs = [
            m.mastery_probability
            for m in (
                db_session.query(TopicMastery)
                .join(Topic, TopicMastery.topic_id == Topic.id)
                .filter(TopicMastery.user_id == user.id, Topic.course_id.in_(course_ids))
                .all()
            )
        ]
        return sum(probs) / len(probs)

    c_net_os = get_avg_mastery(user_c, net_os_ids)
    c_oops_sql = get_avg_mastery(user_c, oops_sql_ids)

    d_net_os = get_avg_mastery(user_d, net_os_ids)
    d_oops_sql = get_avg_mastery(user_d, oops_sql_ids)

    # Group C is stronger on Networks/OS
    assert c_net_os > d_net_os

    # Group D is stronger on OOPS/SQL
    assert d_oops_sql > c_oops_sql


def test_reproducible_identical_mastery(db_session: Session):
    """Two independent seeding runs with the same random seed produce identical mastery probabilities."""
    # First run
    seed_synthetic_learners(db_session, num_learners=10, dry_run=False, seed=42)
    masteries_run1 = {
        (u.email, m.topic_id): m.mastery_probability
        for u in db_session.query(User).filter(User.email.like("%@synthetic.learnwise.test")).all()
        for m in db_session.query(TopicMastery).filter_by(user_id=u.id).all()
    }

    # Reset synthetic users
    reset_synthetic_learners(db_session, confirm_yes=True)
    assert db_session.query(User).filter(User.email.like("%@synthetic.learnwise.test")).count() == 0

    # Second run with same seed
    seed_synthetic_learners(db_session, num_learners=10, dry_run=False, seed=42)
    masteries_run2 = {
        (u.email, m.topic_id): m.mastery_probability
        for u in db_session.query(User).filter(User.email.like("%@synthetic.learnwise.test")).all()
        for m in db_session.query(TopicMastery).filter_by(user_id=u.id).all()
    }

    assert len(masteries_run1) == len(masteries_run2)
    for key, prob1 in masteries_run1.items():
        assert prob1 == masteries_run2[key]


def test_reset_synthetic_removes_only_synthetic_users(db_session: Session, test_learner: User):
    """--reset-synthetic deletes only synthetic learners and preserves legitimate/demo users."""
    seed_synthetic_learners(db_session, num_learners=10, dry_run=False)

    assert (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .count()
        == 10
    )
    assert db_session.query(User).filter_by(id=test_learner.id).first() is not None

    # Reset with confirm_yes=True
    result = reset_synthetic_learners(db_session, confirm_yes=True)
    assert result["deleted_users"] == 10

    # Verify all synthetic users removed
    assert (
        db_session.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .count()
        == 0
    )
    # Verify non-synthetic user is preserved
    preserved = db_session.query(User).filter_by(id=test_learner.id).first()
    assert preserved is not None
    assert preserved.email == test_learner.email
