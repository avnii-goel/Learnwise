"""Database integration tests for recommender service using FakeEmbedder.

Covers docs/RECOMMENDER.md and Chunk 6.4 (d):
- Weak learner gets easy resources and hard is excluded when easier exist
- Brand-new learner gets 'start here' topics with collaborative_available=False
- Reason string never contains peer name or email
- Idempotency: same call twice gives identical output
- content_only strategy gives collaborative_available=False
- Unknown strategy raises ValueError
"""

import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.course import Course
from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.models.topic_mastery import TopicMastery
from app.models.recommendation_impression import RecommendationImpression
from app.recommender.embedding import FakeEmbedder, build_resource_text, embedding_hash
from app.recommender.service import recommend_for_user
from app.utils.security import hash_password


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def test_setup(db_session: Session, fake_embedder: FakeEmbedder):
    """Sets up base courses, topics, and embedded learning resources for testing."""
    # Find existing seeded topics in Computer Networks
    t1 = db_session.query(Topic).filter_by(title="Network Fundamentals").first()
    t2 = db_session.query(Topic).filter_by(title="OSI & TCP/IP Models").first()
    assert t1 is not None and t2 is not None

    def _create_resource(topic: Topic, title: str, difficulty: str, url: str) -> LearningResource:
        desc = f"Comprehensive description for {title} with at least thirty characters."
        text = build_resource_text(topic.title, title, desc)
        vec = fake_embedder.embed([text])[0]
        h = embedding_hash(fake_embedder.model_name, text)
        res = LearningResource(
            topic_id=topic.id,
            title=title,
            description=desc,
            resource_type="article",
            url=url,
            difficulty=difficulty,
            order=1,
            embedding=vec,
            embedding_hash=h,
        )
        db_session.add(res)
        return res

    # Create resources for Topic 1: easy, medium, hard
    r_easy = _create_resource(t1, "Easy Net Basics", "easy", "https://example.com/net-easy")
    r_med = _create_resource(t1, "Medium Net Routing", "medium", "https://example.com/net-med")
    r_hard = _create_resource(t1, "Hard Net Kernel", "hard", "https://example.com/net-hard")

    # Create resources for Topic 2: easy, medium
    r2_easy = _create_resource(t2, "Easy OSI Intro", "easy", "https://example.com/osi-easy")
    r2_med = _create_resource(t2, "Medium OSI Stack", "medium", "https://example.com/osi-med")

    db_session.commit()

    return {
        "t1": t1,
        "t2": t2,
        "r_easy": r_easy,
        "r_med": r_med,
        "r_hard": r_hard,
        "r2_easy": r2_easy,
        "r2_med": r2_med,
    }


def test_weak_learner_gets_easy_first_and_hard_excluded(
    db_session: Session,
    test_setup: dict,
    fake_embedder: FakeEmbedder
):
    """A weak learner (target rank 0) receives easy/medium resources; hard (rank 2) is excluded."""
    t1 = test_setup["t1"]
    user = User(
        email="weak.learner@test.com",
        name="Weak Learner",
        password_hash=hash_password("password123"),
        role="learner",
    )
    db_session.add(user)
    db_session.flush()

    # User has weak mastery on t1 (p=0.20, answers=2 -> status 'weak')
    mastery = TopicMastery(
        user_id=user.id,
        topic_id=t1.id,
        mastery_probability=0.20,
        total_answers=2,
        correct_answers=0,
    )
    db_session.add(mastery)
    db_session.commit()

    result = recommend_for_user(db_session, user.id, strategy="hybrid", embedder=fake_embedder)

    t1_items = [it for it in result.items if it.topic_id == t1.id]
    assert len(t1_items) > 0

    difficulties = [it.resource.difficulty for it in t1_items]
    # Hard (rank 2) must be excluded because target is easy (rank 0) and 2 - 0 >= 2
    assert "hard" not in difficulties
    assert "easy" in difficulties
    # First item should be easy (best difficulty fit = 1.0 vs medium 0.5)
    assert t1_items[0].resource.difficulty == "easy"


def test_brand_new_learner_gets_start_here_and_no_collab(
    db_session: Session,
    test_setup: dict,
    fake_embedder: FakeEmbedder
):
    """A brand-new learner gets start_here focus topics with collaborative_available=False."""
    user = User(
        email="fresh.learner@test.com",
        name="Fresh Learner",
        password_hash=hash_password("password123"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()

    result = recommend_for_user(db_session, user.id, strategy="hybrid", embedder=fake_embedder)

    assert result.collaborative_available is False
    assert len(result.items) > 0

    for item in result.items:
        assert item.target_kind == "start_here"
        # Reason must include unattempted explanation clauses
        assert "You have not started" in item.reason
        assert "all prerequisite competencies have been satisfied" in item.reason


def test_reason_string_never_contains_peer_name_or_email(
    db_session: Session,
    test_setup: dict,
    fake_embedder: FakeEmbedder
):
    """Reason text must never leak peer names or email addresses."""
    t1 = test_setup["t1"]
    r_easy = test_setup["r_easy"]

    # Target learner
    user = User(
        email="main.learner@test.com",
        name="Main Learner",
        password_hash=hash_password("password123"),
        role="learner",
    )
    # Peer learner with unique names
    peer = User(
        email="confidential.peer@test.com",
        name="Sherlock Holmes",
        password_hash=hash_password("password123"),
        role="learner",
    )
    db_session.add_all([user, peer])
    db_session.flush()

    # User has weak mastery on t1, t2, t3 (for shared breadth)
    t2 = test_setup["t2"]
    t3 = db_session.query(Topic).filter_by(title="Data Link Layer").first()
    assert t3 is not None

    for t in [t1, t2, t3]:
        db_session.add(TopicMastery(user_id=user.id, topic_id=t.id, mastery_probability=0.30, total_answers=3, correct_answers=1))
        db_session.add(TopicMastery(user_id=peer.id, topic_id=t.id, mastery_probability=0.85, total_answers=5, correct_answers=4))

    # Add a clicked impression for peer on r_easy with improvement
    import uuid
    from datetime import datetime, timezone
    imp = RecommendationImpression(
        user_id=peer.id,
        resource_id=r_easy.id,
        topic_id=t1.id,
        request_id=uuid.uuid4(),
        strategy="hybrid",
        rank=1,
        score=0.90,
        mastery_at_shown=0.20,  # Improved from 0.20 to 0.85 (> 0.20 + 0.05)
        components={},
        reason="Test",
        clicked_at=datetime.now(timezone.utc),
    )
    db_session.add(imp)
    db_session.commit()

    result = recommend_for_user(db_session, user.id, strategy="hybrid", embedder=fake_embedder)

    for item in result.items:
        # Strict privacy checks: never contain peer's identity
        assert "Sherlock" not in item.reason
        assert "Holmes" not in item.reason
        assert "confidential.peer@test.com" not in item.reason


def test_same_call_twice_gives_identical_output(
    db_session: Session,
    test_setup: dict,
    fake_embedder: FakeEmbedder
):
    """Calling recommend_for_user twice consecutively produces strictly identical output."""
    user = User(
        email="stable.learner@test.com",
        name="Stable Learner",
        password_hash=hash_password("password123"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()

    res1 = recommend_for_user(db_session, user.id, strategy="hybrid", embedder=fake_embedder)
    res2 = recommend_for_user(db_session, user.id, strategy="hybrid", embedder=fake_embedder)

    assert res1.strategy == res2.strategy
    assert res1.collaborative_available == res2.collaborative_available
    assert len(res1.items) == len(res2.items)

    for it1, it2 in zip(res1.items, res2.items):
        assert it1.resource_id == it2.resource_id
        assert it1.rank == it2.rank
        assert pytest.approx(it1.score, 1e-6) == it2.score
        assert it1.reason == it2.reason
        assert it1.components == it2.components


def test_content_only_strategy_collaborative_available_is_false(
    db_session: Session,
    test_setup: dict,
    fake_embedder: FakeEmbedder
):
    """content_only strategy always sets collaborative_available=False and collab weight=0."""
    user = User(
        email="content.learner@test.com",
        name="Content Learner",
        password_hash=hash_password("password123"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()

    result = recommend_for_user(db_session, user.id, strategy="content_only", embedder=fake_embedder)

    assert result.strategy == "content_only"
    assert result.collaborative_available is False
    for item in result.items:
        assert item.components["collaborative"] == 0.0


def test_unknown_strategy_raises_value_error(db_session: Session, test_setup: dict):
    """Passing an unsupported strategy string raises a clear ValueError."""
    with pytest.raises(ValueError, match="Unknown recommendation strategy"):
        recommend_for_user(db_session, 1, strategy="random_strategy")
