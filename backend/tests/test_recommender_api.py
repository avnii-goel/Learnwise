"""End-to-end integration tests for recommendations API and click simulation script.

Covers Chunk 6.5 deliverables and docs/RECOMMENDER.md Sections 11-14:
- POST /api/recommendations/me 9-item cap
- POST /api/recommendations/me response structure and impression table persistence
- strategy=content_only setting collaborative_available=False
- Error handling on unknown strategy (400) and unauthenticated access (401)
- Click recording: returns resource URL and timestamp
- Click idempotency: double click preserves the original timestamp
- Click authorization: cross-user click returns 404
- Click non-existent impression ID returns 404
- Learner isolation: impressions never visible or editable across users
- Collaborative available boost fixture verification (hybrid > content_only)
- simulate_recommendation_clicks script:
  - Refusal when synthetic learners are missing
  - Dry-run writes nothing
  - Rebuild is deterministic across runs with identical seed
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session
from fastapi import status

from app.models.learningresource import LearningResource
from app.models.recommendation_impression import RecommendationImpression
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.user import User
from app.recommender.embedding import FakeEmbedder, build_resource_text, embedding_hash
from app.utils.jwt import create_access_token
from app.utils.security import hash_password
import scripts.simulate_recommendation_clicks as sim_module
from scripts.simulate_recommendation_clicks import simulate_recommendation_clicks


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def recommender_test_resources(db_session: Session, fake_embedder: FakeEmbedder):
    """Seeds embedded resources across Network Fundamentals, OSI Model, and Data Link Layer."""
    t1 = db_session.query(Topic).filter_by(title="Network Fundamentals").first()
    t2 = db_session.query(Topic).filter_by(title="OSI & TCP/IP Models").first()
    t3 = db_session.query(Topic).filter_by(title="Data Link Layer").first()
    t4 = db_session.query(Topic).filter_by(title="Network Layer").first()
    assert t1 is not None and t2 is not None and t3 is not None and t4 is not None

    created = []

    def _add_res(topic: Topic, title: str, diff: str, url: str) -> LearningResource:
        desc = f"Comprehensive description for {title} containing at least thirty characters."
        text = build_resource_text(topic.title, title, desc)
        vec = fake_embedder.embed([text])[0]
        h = embedding_hash(fake_embedder.model_name, text)
        r = LearningResource(
            topic_id=topic.id,
            title=title,
            description=desc,
            resource_type="article",
            url=url,
            difficulty=diff,
            order=1,
            embedding=vec,
            embedding_hash=h,
        )
        db_session.add(r)
        created.append(r)
        return r

    # Topic 1 resources (easy, medium, hard)
    r1_easy = _add_res(t1, "Net Fundamentals Easy Guide", "easy", "https://example.com/net-easy")
    r1_med = _add_res(t1, "Net Fundamentals Core Concepts", "medium", "https://example.com/net-med")
    r1_hard = _add_res(t1, "Net Fundamentals Advanced Kernel", "hard", "https://example.com/net-hard")

    # Topic 2 resources
    r2_easy = _add_res(t2, "OSI Model Explained Simply", "easy", "https://example.com/osi-easy")
    r2_med = _add_res(t2, "TCP/IP Stack Deep Dive", "medium", "https://example.com/osi-med")

    # Topic 3 resources
    r3_easy = _add_res(t3, "Ethernet & Data Link Basics", "easy", "https://example.com/datalink-easy")

    # Topic 4 resources (to ensure >3 candidate topics with resources)
    r4_easy = _add_res(t4, "IP Addressing & Subnets", "easy", "https://example.com/ip-easy")

    db_session.commit()
    for r in created:
        db_session.refresh(r)

    return {
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "t4": t4,
        "r1_easy": r1_easy,
        "r1_med": r1_med,
        "r1_hard": r1_hard,
        "r2_easy": r2_easy,
        "r2_med": r2_med,
        "r3_easy": r3_easy,
        "r4_easy": r4_easy,
    }


# ============================================================================
# 1. Recommendation Endpoint Tests (POST /api/recommendations/me)
# ============================================================================

def test_recommendations_me_caps_at_most_nine_items(
    client,
    learner_token,
    recommender_test_resources,
):
    """POST /api/recommendations/me returns at most 9 items (<=3 target topics * <=3 resources)."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/recommendations/me?strategy=hybrid", headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    items = data["items"]
    assert len(items) <= 9
    assert len(items) > 0


def test_recommendations_me_returns_valid_structure_and_logs_impressions(
    client,
    learner_token,
    db_session: Session,
    recommender_test_resources,
):
    """POST /api/recommendations/me returns complete item schemas and persists audit rows."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/recommendations/me?strategy=hybrid", headers=headers)
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    assert "request_id" in data
    assert data["strategy"] == "hybrid"
    assert "collaborative_available" in data
    items = data["items"]

    # Verify every required field is present on each item
    for idx, it in enumerate(items, start=1):
        assert it["rank"] == idx
        assert "impression_id" in it
        assert isinstance(it["impression_id"], int)

        # Resource details
        res = it["resource"]
        assert "id" in res
        assert "title" in res
        assert "description" in res
        assert "resource_type" in res
        assert "url" in res
        assert "difficulty" in res

        # Topic details
        top = it["topic"]
        assert "id" in top
        assert "title" in top

        # Scoring & components
        assert "score" in it
        assert "mastery" in it
        assert "status" in it
        assert "reason" in it
        comp = it["components"]
        assert "need" in comp
        assert "semantic" in comp
        assert "difficulty_fit" in comp
        assert "collaborative" in comp

    # Verify database audit logging in recommendation_impressions
    req_uuid = data["request_id"]
    impressions = (
        db_session.query(RecommendationImpression)
        .filter(RecommendationImpression.request_id == req_uuid)
        .order_by(RecommendationImpression.rank.asc())
        .all()
    )
    assert len(impressions) == len(items)

    for it, imp in zip(items, impressions):
        assert imp.id == it["impression_id"]
        assert imp.strategy == "hybrid"
        assert imp.rank == it["rank"]
        assert imp.score == pytest.approx(it["score"], 1e-4)
        assert imp.is_synthetic is False
        assert imp.clicked_at is None
        assert imp.shown_at is not None


def test_recommendations_me_strategy_content_only_collaborative_false(client, learner_token):
    """strategy=content_only reports collaborative_available=False and sets collaborative weight=0."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/recommendations/me?strategy=content_only", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["strategy"] == "content_only"
    assert data["collaborative_available"] is False
    for it in data["items"]:
        assert it["components"]["collaborative"] == 0.0


def test_recommendations_me_unknown_strategy_returns_400(client, learner_token):
    """Passing an unknown strategy string returns 400 Bad Request with a clear message."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    bad_resp = client.post("/api/recommendations/me?strategy=unsupported_strategy", headers=headers)
    assert bad_resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unknown recommendation strategy 'unsupported_strategy'" in bad_resp.json()["detail"]


def test_recommendations_me_unauthenticated_returns_401(client):
    """Calling /api/recommendations/me without a Bearer token returns 401 Unauthorized."""
    unauth_resp = client.post("/api/recommendations/me")
    assert unauth_resp.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# 2. Click Recording Tests (POST /api/recommendations/impressions/{id}/click)
# ============================================================================

def test_click_impression_returns_resource_url_and_timestamp(
    client,
    learner_token,
    db_session: Session,
    recommender_test_resources,
):
    """Clicking an impression returns the resource_url and recorded clicked_at timestamp."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/recommendations/me", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    item = resp.json()["items"][0]
    imp_id = item["impression_id"]
    expected_url = item["resource"]["url"]

    click_resp = client.post(f"/api/recommendations/impressions/{imp_id}/click", headers=headers)
    assert click_resp.status_code == status.HTTP_200_OK
    data = click_resp.json()
    assert data["impression_id"] == imp_id
    assert data["resource_url"] == expected_url
    assert data["clicked_at"] is not None


def test_click_impression_idempotency_keeps_first_timestamp(
    client,
    learner_token,
    recommender_test_resources,
):
    """Double-clicking an impression is idempotent and preserves the initial clicked_at timestamp."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    resp = client.post("/api/recommendations/me", headers=headers)
    item = resp.json()["items"][0]
    imp_id = item["impression_id"]

    click_1 = client.post(f"/api/recommendations/impressions/{imp_id}/click", headers=headers)
    assert click_1.status_code == status.HTTP_200_OK
    first_clicked_at = click_1.json()["clicked_at"]

    click_2 = client.post(f"/api/recommendations/impressions/{imp_id}/click", headers=headers)
    assert click_2.status_code == status.HTTP_200_OK
    assert click_2.json()["clicked_at"] == first_clicked_at


def test_click_impression_cross_user_returns_404(
    client,
    learner_token,
    db_session: Session,
    recommender_test_resources,
):
    """Learner B attempting to click Learner A's impression receives 404 Not Found."""
    headers_a = {"Authorization": f"Bearer {learner_token}"}
    resp_a = client.post("/api/recommendations/me", headers=headers_a)
    imp_id = resp_a.json()["items"][0]["impression_id"]

    learner_b = User(
        name="Learner B",
        email="learner.b@learnwise.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add(learner_b)
    db_session.commit()
    token_b = create_access_token(learner_b.id)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    click_b_resp = client.post(f"/api/recommendations/impressions/{imp_id}/click", headers=headers_b)
    assert click_b_resp.status_code == status.HTTP_404_NOT_FOUND
    assert click_b_resp.json()["detail"] == "Impression not found"


def test_click_impression_nonexistent_id_returns_404(client, learner_token):
    """Attempting to click a non-existent impression ID returns 404 Not Found."""
    headers = {"Authorization": f"Bearer {learner_token}"}
    click_nonexistent = client.post("/api/recommendations/impressions/999999/click", headers=headers)
    assert click_nonexistent.status_code == status.HTTP_404_NOT_FOUND


def test_learner_isolation_impressions_never_shared(
    client,
    db_session: Session,
    recommender_test_resources,
):
    """Learners only see and affect their own impressions."""
    u1 = User(name="User 1", email="u1@test.com", password_hash=hash_password("pw1"), role="learner")
    u2 = User(name="User 2", email="u2@test.com", password_hash=hash_password("pw2"), role="learner")
    db_session.add_all([u1, u2])
    db_session.commit()

    tok1 = create_access_token(u1.id)
    tok2 = create_access_token(u2.id)

    resp1 = client.post("/api/recommendations/me", headers={"Authorization": f"Bearer {tok1}"})
    resp2 = client.post("/api/recommendations/me", headers={"Authorization": f"Bearer {tok2}"})

    assert resp1.status_code == status.HTTP_200_OK
    assert resp2.status_code == status.HTTP_200_OK

    imps1 = db_session.query(RecommendationImpression).filter_by(user_id=u1.id).all()
    imps2 = db_session.query(RecommendationImpression).filter_by(user_id=u2.id).all()

    assert len(imps1) > 0 and all(i.user_id == u1.id for i in imps1)
    assert len(imps2) > 0 and all(i.user_id == u2.id for i in imps2)


def test_collaborative_available_boost_hybrid_greater_than_content_only(
    client,
    db_session: Session,
    recommender_test_resources,
):
    """Resource clicked by an improved similar neighbour scores higher under hybrid than content_only."""
    t1 = recommender_test_resources["t1"]
    t2 = recommender_test_resources["t2"]
    t3 = recommender_test_resources["t3"]
    r1_easy = recommender_test_resources["r1_easy"]

    target_user = User(
        name="Target Learner",
        email="target.learner@learnwise.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    peer_user = User(
        name="Peer Learner",
        email="peer.learner@learnwise.com",
        password_hash=hash_password("Pass123!"),
        role="learner",
    )
    db_session.add_all([target_user, peer_user])
    db_session.flush()

    for t in [t1, t2, t3]:
        db_session.add(TopicMastery(user_id=target_user.id, topic_id=t.id, mastery_probability=0.30, total_answers=3, correct_answers=1))
        db_session.add(TopicMastery(user_id=peer_user.id, topic_id=t.id, mastery_probability=0.40, total_answers=5, correct_answers=2))

    import uuid
    db_session.add(
        RecommendationImpression(
            user_id=peer_user.id,
            resource_id=r1_easy.id,
            topic_id=t1.id,
            request_id=uuid.uuid4(),
            strategy="hybrid",
            rank=1,
            score=0.90,
            mastery_at_shown=0.20,
            components={},
            reason="Peer clicked",
            shown_at=datetime.now(timezone.utc),
            clicked_at=datetime.now(timezone.utc),
            is_synthetic=False,
        )
    )
    db_session.commit()

    token = create_access_token(target_user.id)
    headers = {"Authorization": f"Bearer {token}"}

    resp_hybrid = client.post("/api/recommendations/me?strategy=hybrid", headers=headers)
    assert resp_hybrid.status_code == status.HTTP_200_OK
    data_hybrid = resp_hybrid.json()
    assert data_hybrid["collaborative_available"] is True

    item_hybrid = next((it for it in data_hybrid["items"] if it["resource"]["id"] == r1_easy.id), None)
    assert item_hybrid is not None
    assert item_hybrid["components"]["collaborative"] > 0.0

    resp_content = client.post("/api/recommendations/me?strategy=content_only", headers=headers)
    assert resp_content.status_code == status.HTTP_200_OK
    data_content = resp_content.json()

    item_content = next((it for it in data_content["items"] if it["resource"]["id"] == r1_easy.id), None)
    assert item_content is not None
    assert item_content["components"]["collaborative"] == 0.0

    assert item_hybrid["score"] > item_content["score"]


# ============================================================================
# 3. Click Simulation Script Tests (simulate_recommendation_clicks.py)
# ============================================================================

def test_simulation_script_refuses_when_synthetic_learners_missing(
    db_session: Session,
    fake_embedder,
):
    """simulate_recommendation_clicks raises RuntimeError when expected synthetic learners are missing."""
    with pytest.raises(RuntimeError, match="Synthetic learner validation failed"):
        simulate_recommendation_clicks(db_session, embedder=fake_embedder)


def test_simulation_script_dry_run_writes_nothing(
    db_session: Session,
    recommender_test_resources,
    fake_embedder,
    monkeypatch,
):
    """simulate_recommendation_clicks with dry_run=True computes statistics and writes zero rows."""
    u1 = User(
        name="Synthetic Learner 01",
        email="synthetic-01@synthetic.learnwise.test",
        password_hash=hash_password("pw"),
        role="learner",
    )
    u2 = User(
        name="Synthetic Learner 02",
        email="synthetic-02@synthetic.learnwise.test",
        password_hash=hash_password("pw"),
        role="learner",
    )
    db_session.add_all([u1, u2])
    db_session.commit()

    monkeypatch.setattr(sim_module, "EXPECTED_SYNTHETIC_LEARNERS", 2)

    dry_res = simulate_recommendation_clicks(
        db_session,
        dry_run=True,
        rebuild=False,
        embedder=fake_embedder,
    )
    assert dry_res["impressions"] > 0
    assert dry_res["dry_run"] is True
    assert db_session.query(RecommendationImpression).count() == 0


def test_simulation_script_rebuild_is_deterministic(
    db_session: Session,
    recommender_test_resources,
    fake_embedder,
    monkeypatch,
):
    """simulate_recommendation_clicks with rebuild=True wipes synthetic rows and reproduces identically."""
    u1 = User(
        name="Synthetic Learner 01",
        email="synthetic-01@synthetic.learnwise.test",
        password_hash=hash_password("pw"),
        role="learner",
    )
    u2 = User(
        name="Synthetic Learner 02",
        email="synthetic-02@synthetic.learnwise.test",
        password_hash=hash_password("pw"),
        role="learner",
    )
    db_session.add_all([u1, u2])
    db_session.commit()

    monkeypatch.setattr(sim_module, "EXPECTED_SYNTHETIC_LEARNERS", 2)

    run1 = simulate_recommendation_clicks(
        db_session,
        dry_run=False,
        rebuild=False,
        seed=42,
        embedder=fake_embedder,
    )
    assert run1["impressions"] > 0
    synthetic_rows_1 = (
        db_session.query(RecommendationImpression)
        .filter(RecommendationImpression.is_synthetic.is_(True))
        .order_by(RecommendationImpression.user_id.asc(), RecommendationImpression.rank.asc())
        .all()
    )
    assert len(synthetic_rows_1) == run1["impressions"]
    assert all(r.is_synthetic is True for r in synthetic_rows_1)

    signatures_1 = [
        (r.user_id, r.resource_id, r.rank, pytest.approx(r.score, 1e-4), r.clicked_at is not None, r.mastery_at_shown)
        for r in synthetic_rows_1
    ]

    run2 = simulate_recommendation_clicks(
        db_session,
        dry_run=False,
        rebuild=True,
        seed=42,
        embedder=fake_embedder,
    )
    assert run2["deleted"] == len(synthetic_rows_1)
    assert run2["impressions"] == run1["impressions"]
    assert run2["clicks"] == run1["clicks"]
    assert run2["helped"] == run1["helped"]

    synthetic_rows_2 = (
        db_session.query(RecommendationImpression)
        .filter(RecommendationImpression.is_synthetic.is_(True))
        .order_by(RecommendationImpression.user_id.asc(), RecommendationImpression.rank.asc())
        .all()
    )
    signatures_2 = [
        (r.user_id, r.resource_id, r.rank, pytest.approx(r.score, 1e-4), r.clicked_at is not None, r.mastery_at_shown)
        for r in synthetic_rows_2
    ]
    assert len(signatures_1) == len(signatures_2)
    for s1, s2 in zip(signatures_1, signatures_2):
        assert s1 == s2
