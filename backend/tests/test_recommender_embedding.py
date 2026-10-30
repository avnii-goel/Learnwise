"""Tests for recommender config, embedding protocol, FakeEmbedder, and embed_resources script.

Ensures strict test isolation: uses FakeEmbedder only (no network or model downloads).
Reference: docs/RECOMMENDER.md Section 3 and Chunk 6.3.
"""

import math
import os
import pytest
from sqlalchemy.orm import Session

from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.recommender import config
from app.recommender.embedding import (
    Embedder,
    FakeEmbedder,
    get_embedder,
    build_resource_text,
    embedding_hash,
)
from scripts.embed_resources import embed_resources


def cosine_sim(u: list[float], v: list[float]) -> float:
    return sum(a * b for a, b in zip(u, v))


# ============================================================================
# 1. Configuration Constants & Mastery Threshold Import
# ============================================================================

def test_recommender_config_constants_and_imports():
    """Validates that all specified constants and Phase 5 imports exist in config."""
    assert config.MODEL_NAME == "sentence-transformers/all-MiniLM-L6-v2"
    assert config.FALLBACK_MODEL_NAME == "BAAI/bge-small-en-v1.5"
    assert config.EMBEDDING_DIM == 384
    assert config.MAX_TARGET_TOPICS == 3
    assert config.RESOURCES_PER_TOPIC == 3
    assert config.DIFFICULTY_TARGET_EASY_MAX == 0.40
    assert config.DIFFICULTY_TARGET_MEDIUM_MAX == 0.70
    assert config.DIFFICULTY_THRESHOLDS == (0.40, 0.70)
    assert config.NOT_ATTEMPTED_NEED == 0.50
    assert config.K_NEIGHBORS == 10
    assert config.MIN_SHARED_TOPICS == 3
    assert config.MIN_SIMILARITY == 0.75
    assert config.IMPROVEMENT_MARGIN == 0.05
    assert config.WRONG_ANSWERS_IN_QUERY == 3

    # Strategies and component weights
    assert "hybrid" in config.STRATEGIES
    assert "content_only" in config.STRATEGIES
    assert config.STRATEGIES["hybrid"] == {
        "need": 0.30,
        "semantic": 0.30,
        "difficulty": 0.15,
        "collab": 0.25,
    }
    assert config.STRATEGIES["content_only"] == {
        "need": 0.40,
        "semantic": 0.40,
        "difficulty": 0.20,
        "collab": 0.0,
    }

    # Imported Phase 5 mastery status thresholds
    assert config.STATUS_NOT_ATTEMPTED == "not_attempted"
    assert config.STATUS_WEAK == "weak"
    assert config.STATUS_DEVELOPING == "developing"
    assert config.STATUS_STRONG == "strong"
    assert config.THRESHOLD_WEAK == 0.40
    assert config.THRESHOLD_STRONG == 0.80
    assert config.MIN_ANSWERS_STRONG == 3


# ============================================================================
# 2. FakeEmbedder & Helper Functions
# ============================================================================

def test_fake_embedder_deterministic_length_and_norm():
    """FakeEmbedder is deterministic across multiple calls, length 384, norm 1.0."""
    embedder = FakeEmbedder()
    assert embedder.model_name == "fake-hash-384"
    assert isinstance(embedder, Embedder)

    texts = [
        "Network fundamentals and TCP/IP protocol suite.",
        "Relational database management systems and indexing.",
    ]

    v1 = embedder.embed(texts)
    v2 = embedder.embed(texts)

    # Determinism across calls
    assert v1 == v2

    for vec in v1:
        assert len(vec) == 384
        norm = math.sqrt(sum(x * x for x in vec))
        assert pytest.approx(norm, 1e-6) == 1.0


def test_fake_embedder_word_overlap_similarity():
    """Texts sharing words have strictly higher cosine similarity than unrelated texts."""
    embedder = FakeEmbedder()

    t1 = "TCP connection three-way handshake protocol"
    t2 = "How does the TCP handshake work during connection setup"
    t3 = "Binary search trees maintain keys in logarithmic height"

    vectors = embedder.embed([t1, t2, t3])
    v1, v2, v3 = vectors[0], vectors[1], vectors[2]

    sim_1_2 = cosine_sim(v1, v2)
    sim_1_3 = cosine_sim(v1, v3)
    sim_2_3 = cosine_sim(v2, v3)

    assert sim_1_2 > sim_1_3
    assert sim_1_2 > sim_2_3


def test_embedding_hash_changes_on_text_and_model():
    """Hash changes when text changes and when model name changes."""
    h1 = embedding_hash("fake-hash-384", "sample resource text")
    h2 = embedding_hash("fake-hash-384", "sample resource text")
    h3 = embedding_hash("fake-hash-384", "modified resource text")
    h4 = embedding_hash("other-model-384", "sample resource text")

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_build_resource_text():
    """Builds canonical '{topic title}. {resource title}. {resource description}' format."""
    text = build_resource_text(
        "Network Fundamentals",
        "Basics of Networks",
        "A comprehensive primer on network layouts."
    )
    assert text == "Network Fundamentals. Basics of Networks. A comprehensive primer on network layouts."


def test_get_embedder_returns_fake_in_test_environment():
    """get_embedder returns FakeEmbedder when EMBEDDER_BACKEND is fake."""
    embedder = get_embedder()
    assert isinstance(embedder, FakeEmbedder)
    assert embedder.model_name == "fake-hash-384"


# ============================================================================
# 3. embed_resources Script Tests
# ============================================================================

@pytest.fixture
def sample_resources(db_session: Session):
    """Creates sample resources for embedding tests."""
    topic = db_session.query(Topic).filter_by(title="Network Fundamentals").first()
    assert topic is not None, "Topic 'Network Fundamentals' must exist"

    r1 = LearningResource(
        topic_id=topic.id,
        title="Resource 1",
        description="First description with thirty or more characters present.",
        resource_type="article",
        url="https://example.com/r1",
        difficulty="easy",
        order=1,
    )
    r2 = LearningResource(
        topic_id=topic.id,
        title="Resource 2",
        description="Second description with thirty or more characters present.",
        resource_type="video",
        url="https://example.com/r2",
        difficulty="medium",
        order=2,
    )
    r3 = LearningResource(
        topic_id=topic.id,
        title="Resource 3",
        description="Third description with thirty or more characters present.",
        resource_type="tutorial",
        url="https://example.com/r3",
        difficulty="hard",
        order=3,
    )
    db_session.add_all([r1, r2, r3])
    db_session.commit()
    return [r1, r2, r3]


def test_embed_resources_dry_run_writes_nothing(db_session: Session, sample_resources):
    """--dry-run calculates embeddings and reports counts but writes nothing to DB."""
    result = embed_resources(db_session, dry_run=True)
    assert result["total"] == 3
    assert result["embedded"] == 3
    assert result["skipped"] == 0

    # Verify DB still has NULL embeddings
    for r in sample_resources:
        db_session.refresh(r)
        assert r.embedding is None
        assert r.embedding_hash is None


def test_embed_resources_stale_rows_and_idempotency(db_session: Session, sample_resources):
    """Embeds all un-embedded rows, re-embeds only changed rows, skips unchanged."""
    r1, r2, r3 = sample_resources

    # 1. Initial run: all 3 embedded
    res1 = embed_resources(db_session, dry_run=False)
    assert res1["embedded"] == 3
    assert res1["skipped"] == 0

    # Verify embeddings persisted
    db_session.refresh(r1)
    db_session.refresh(r2)
    db_session.refresh(r3)
    assert len(r1.embedding) == 384
    assert r1.embedding_hash is not None
    original_h1 = r1.embedding_hash
    original_h2 = r2.embedding_hash

    # 2. Second run with no changes: embeds 0, skips 3
    res2 = embed_resources(db_session, dry_run=False)
    assert res2["embedded"] == 0
    assert res2["skipped"] == 3

    # 3. Modify r1's description: only r1 becomes stale
    r1.description = "Updated description with significantly altered words for testing."
    db_session.commit()

    res3 = embed_resources(db_session, dry_run=False)
    assert res3["embedded"] == 1
    assert res3["skipped"] == 2

    # Verify r1 hash changed, r2 hash remained unchanged
    db_session.refresh(r1)
    db_session.refresh(r2)
    assert r1.embedding_hash != original_h1
    assert r2.embedding_hash == original_h2


def test_embed_resources_force_all_reembeds_everything(db_session: Session, sample_resources):
    """--all forces re-embedding of every row even if hash matches."""
    # First embed all rows
    embed_resources(db_session, dry_run=False)

    # Force all
    res = embed_resources(db_session, dry_run=False, force_all=True)
    assert res["embedded"] == 3
    assert res["skipped"] == 0


def test_second_embed_run_with_nothing_changed_embeds_zero_rows(db_session: Session, sample_resources):
    """A second run with nothing changed embeds 0 rows and skips all."""
    # Initial run embeds all rows
    first_run = embed_resources(db_session, dry_run=False)
    assert first_run["embedded"] == len(sample_resources)

    # Second run without modifications
    second_run = embed_resources(db_session, dry_run=False)
    assert second_run["embedded"] == 0
    assert second_run["skipped"] == len(sample_resources)


