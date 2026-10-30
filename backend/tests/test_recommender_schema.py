import uuid
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.course import Course
from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.models.topic_prerequisite import TopicPrerequisite
from app.models.recommendation_impression import RecommendationImpression
from app.models.user import User
from app.utils.security import hash_password


def test_schema_tables_and_columns_exist(db_session):
    """Verifies that the new recommender tables and modified columns exist in the database."""
    inspector = inspect(db_session.bind)
    tables = inspector.get_table_names()

    # 1. Assert new tables exist
    assert "topic_prerequisites" in tables
    assert "recommendation_impressions" in tables

    # 2. Check topic_prerequisites columns
    prereq_cols = {col["name"]: col for col in inspector.get_columns("topic_prerequisites")}
    assert "topic_id" in prereq_cols
    assert "prerequisite_topic_id" in prereq_cols

    # 3. Check recommendation_impressions columns
    imp_cols = {col["name"]: col for col in inspector.get_columns("recommendation_impressions")}
    expected_imp_cols = [
        "id", "user_id", "resource_id", "topic_id", "request_id",
        "strategy", "rank", "score", "mastery_at_shown", "components",
        "reason", "shown_at", "clicked_at", "is_synthetic"
    ]
    for col_name in expected_imp_cols:
        assert col_name in imp_cols, f"Column '{col_name}' missing from recommendation_impressions"

    # 4. Check learning_resources columns
    lr_cols = {col["name"]: col for col in inspector.get_columns("learning_resources")}
    assert "difficulty" in lr_cols
    assert "embedding" in lr_cols
    assert "embedding_hash" in lr_cols


def test_unique_topic_id_url_rejects_duplicate(db_session):
    """Verifies that learning_resources rejects duplicate (topic_id, url) pairs."""
    topic = db_session.query(Topic).first()
    assert topic is not None

    url = "https://learnwise.test/resources/unique-test-resource"
    res1 = LearningResource(
        topic_id=topic.id,
        title="Resource 1",
        description="First instance",
        resource_type="article",
        url=url,
        order=1,
        difficulty="easy",
    )
    db_session.add(res1)
    db_session.commit()

    res2 = LearningResource(
        topic_id=topic.id,
        title="Resource 2",
        description="Duplicate URL instance",
        resource_type="tutorial",
        url=url,
        order=2,
        difficulty="medium",
    )
    db_session.add(res2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_self_prerequisite_check_rejects_identical_topic_ids(db_session):
    """Verifies that topic_prerequisites rejects topic_id == prerequisite_topic_id via check constraint."""
    topic = db_session.query(Topic).first()
    assert topic is not None

    self_prereq = TopicPrerequisite(
        topic_id=topic.id,
        prerequisite_topic_id=topic.id,
    )
    db_session.add(self_prereq)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_vector_storage_and_retrieval_384_dimensions(db_session):
    """Verifies that a 384-dimensional vector embedding can be stored and accurately read back."""
    topic = db_session.query(Topic).first()
    assert topic is not None

    # Generate a sample 384-length float vector
    sample_vector = [(i % 100) / 100.0 for i in range(384)]

    resource = LearningResource(
        topic_id=topic.id,
        title="Vector Embedded Resource",
        description="Resource with 384-dimensional embedding vector",
        resource_type="documentation",
        url="https://learnwise.test/resources/vector-test",
        order=1,
        difficulty="medium",
        embedding=sample_vector,
        embedding_hash="test_sha256_hash_123456",
    )
    db_session.add(resource)
    db_session.commit()
    db_session.refresh(resource)

    # Read back and verify dimensions and values
    assert resource.embedding is not None
    assert len(resource.embedding) == 384
    # pgvector returns numpy array or list-like
    for orig, loaded in zip(sample_vector, resource.embedding):
        assert pytest.approx(orig, abs=1e-5) == float(loaded)


def test_recommendation_impression_storage_and_relationships(db_session):
    """Verifies storing and retrieving a recommendation_impressions row with UUID and JSONB."""
    topic = db_session.query(Topic).first()
    assert topic is not None

    user = User(
        name="Impression Tester",
        email="impression_tester@learnwise.test",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(user)
    db_session.flush()

    resource = LearningResource(
        topic_id=topic.id,
        title="Impression Target Resource",
        description="Target resource",
        resource_type="article",
        url="https://learnwise.test/resources/impression-target",
        order=1,
        difficulty="hard",
    )
    db_session.add(resource)
    db_session.flush()

    req_uuid = uuid.uuid4()
    components_payload = {
        "need": 0.70,
        "semantic": 0.85,
        "difficulty_fit": 1.0,
        "collaborative": 0.25,
    }

    impression = RecommendationImpression(
        user_id=user.id,
        resource_id=resource.id,
        topic_id=topic.id,
        request_id=req_uuid,
        strategy="hybrid",
        rank=1,
        score=0.815,
        mastery_at_shown=0.30,
        components=components_payload,
        reason="Your mastery in this topic is low (30%).",
        is_synthetic=False,
    )
    db_session.add(impression)
    db_session.commit()
    db_session.refresh(impression)

    assert impression.id is not None
    assert impression.request_id == req_uuid
    assert impression.components == components_payload
    assert impression.user.id == user.id
    assert impression.resource.id == resource.id
    assert impression.topic.id == topic.id
    assert impression.is_synthetic is False
    assert impression.shown_at is not None
    assert impression.clicked_at is None

