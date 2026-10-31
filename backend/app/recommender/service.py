"""Recommendation generation service for LearnWise.

Executes target topic selection, misconception-aware query embedding,
difficulty filtering, peer neighborhood attribution, multi-component scoring,
and deterministic explanation assembly.

Zero write operations: this module strictly queries and calculates recommendations.
Reference: docs/RECOMMENDER.md Sections 2, 4-11, 13.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.learningresource import LearningResource
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.recommendation_impression import RecommendationImpression
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_prerequisite import TopicPrerequisite
from app.recommender.config import (
    IMPROVEMENT_MARGIN,
    K_NEIGHBORS,
    MIN_SIMILARITY,
    RESOURCES_PER_TOPIC,
    STATUS_NOT_ATTEMPTED,
    STRATEGIES,
    WRONG_ANSWERS_IN_QUERY,
)
from app.recommender.embedding import Embedder, get_embedder
from app.recommender.scoring import (
    build_reason,
    collaborative_scores,
    difficulty_filter,
    difficulty_fit,
    difficulty_rank,
    difficulty_target,
    hybrid_score,
    minmax_scale,
    normalise_weights,
    pick_neighbours,
    select_targets,
)
from app.services.bkt import classify


@dataclass
class RecommendationItem:
    """An individual ranked learning resource recommendation."""
    resource_id: int
    topic_id: int
    score: float
    rank: int
    components: dict[str, float]
    reason: str
    resource: LearningResource
    target_topic_id: int
    target_kind: str
    redirected_from_topic_id: int | None = None
    mastery: float | None = None
    status: str = STATUS_NOT_ATTEMPTED


@dataclass
class RecommendationResult:
    """Output structure containing recommendations and engine metadata."""
    strategy: str
    collaborative_available: bool
    items: list[RecommendationItem]


def recommend_for_user(
    db: Session,
    user_id: int,
    strategy: str = "hybrid",
    embedder: Embedder | None = None
) -> RecommendationResult:
    """Generates personalized learning resource recommendations for a user.

    Pure read-only query service. Does NOT write to the database.

    Args:
        db: SQLAlchemy database session.
        user_id: Target learner user ID.
        strategy: Recommendation strategy ('hybrid' or 'content_only').
        embedder: Optional custom embedder (defaults to get_embedder()).

    Returns:
        RecommendationResult: Strategy, collaborative availability flag, and ranked items.

    Raises:
        ValueError: If strategy is unknown.
    """
    if strategy not in STRATEGIES:
        allowed = list(STRATEGIES.keys())
        raise ValueError(
            f"Unknown recommendation strategy '{strategy}'. Supported strategies: {allowed}"
        )

    base_weights = STRATEGIES[strategy]
    active_embedder = embedder or get_embedder()

    # 1. Fetch courses, topics, and canonical topic ordering
    courses = db.query(Course).order_by(Course.id.asc()).all()
    topics = (
        db.query(Topic)
        .join(Course, Topic.course_id == Course.id)
        .order_by(Course.id.asc(), Topic.order.asc(), Topic.id.asc())
        .all()
    )
    topic_order = [t.id for t in topics]
    topic_map = {t.id: t for t in topics}

    # 2. Fetch prerequisite graph
    prereq_rows = (
        db.query(TopicPrerequisite.topic_id, TopicPrerequisite.prerequisite_topic_id)
        .all()
    )
    prerequisites: dict[int, list[int]] = defaultdict(list)
    for tid, pid in prereq_rows:
        prerequisites[tid].append(pid)

    # 3. Identify topics that have embedded learning resources
    embedded_topic_ids = set(
        r[0]
        for r in db.query(LearningResource.topic_id)
        .filter(LearningResource.embedding.isnot(None))
        .distinct()
        .all()
    )

    # 4. Fetch target user's topic mastery using Phase 5 classification
    user_mastery_rows = (
        db.query(TopicMastery)
        .filter(TopicMastery.user_id == user_id)
        .all()
    )
    user_mastery_by_topic = {row.topic_id: row for row in user_mastery_rows}

    statuses: dict[int, str] = {}
    mastery_prob: dict[int, float] = {}
    for t in topics:
        row = user_mastery_by_topic.get(t.id)
        total_answers = row.total_answers if row else 0
        p = row.mastery_probability if (row and total_answers > 0) else 0.0
        st = classify(p, total_answers)
        statuses[t.id] = st
        mastery_prob[t.id] = p

    # 5. Select focus target topics
    targets = select_targets(
        statuses=statuses,
        mastery=mastery_prob,
        prerequisites=prerequisites,
        topic_order=topic_order,
        has_resources=embedded_topic_ids,
    )

    if not targets:
        return RecommendationResult(
            strategy=strategy,
            collaborative_available=False,
            items=[]
        )

    # 6. Collaborative Filtering: Peer Neighborhood & Credits
    neighbours: list[tuple[int, float]] = []
    credits: dict[tuple[int, int], int] = {}

    if strategy != "content_only":
        # Load all other learners' mastery profiles (where total_answers > 0)
        peer_mastery_rows = (
            db.query(TopicMastery)
            .filter(TopicMastery.total_answers > 0)
            .all()
        )
        all_learners_mastery: dict[int, dict[int, float]] = defaultdict(dict)
        for row in peer_mastery_rows:
            all_learners_mastery[row.user_id][row.topic_id] = row.mastery_probability

        # Add target user's attempted topics
        target_attempted = {
            tid: p for tid, p in mastery_prob.items()
            if statuses[tid] != STATUS_NOT_ATTEMPTED
        }
        all_learners_mastery[user_id] = target_attempted

        # Identify similar peer neighbors
        neighbours = pick_neighbours(
            target_user_id=user_id,
            all_learners_mastery=all_learners_mastery,
            min_similarity=MIN_SIMILARITY,
            k=K_NEIGHBORS
        )

        if neighbours:
            neighbour_ids = [nid for nid, _ in neighbours]
            # Fetch clicked impressions from neighbors
            impressions = (
                db.query(RecommendationImpression)
                .filter(
                    RecommendationImpression.user_id.in_(neighbour_ids),
                    RecommendationImpression.clicked_at.isnot(None),
                    RecommendationImpression.mastery_at_shown.isnot(None),
                )
                .all()
            )
            for imp in impressions:
                curr_peer_m = (
                    all_learners_mastery.get(imp.user_id, {})
                    .get(imp.topic_id, 0.0)
                )
                if curr_peer_m > (imp.mastery_at_shown + IMPROVEMENT_MARGIN):
                    credits[(imp.user_id, imp.resource_id)] = 1

    # 7. Collect and prepare candidate resources per target topic
    topic_data: list[dict[str, Any]] = []
    all_candidate_resource_ids: list[int] = []

    for target in targets:
        t_rank = difficulty_target(
            target.mastery if target.status != STATUS_NOT_ATTEMPTED else None
        )
        t_diff_str = ["easy", "medium", "hard"][t_rank]

        # Query learner's recent incorrect responses in this topic
        wrong_question_rows = (
            db.query(Question.question_text)
            .join(QuizResponse, QuizResponse.question_id == Question.id)
            .join(QuizAttempt, QuizResponse.attempt_id == QuizAttempt.id)
            .filter(
                QuizAttempt.user_id == user_id,
                QuizAttempt.status == "completed",
                QuizResponse.topic_id == target.topic_id,
                QuizResponse.is_correct == False,
            )
            .order_by(QuizAttempt.completed_at.desc(), QuizResponse.id.desc())
            .limit(WRONG_ANSWERS_IN_QUERY)
            .all()
        )
        wrong_texts = [q[0] for q in wrong_question_rows]
        target_topic_obj = topic_map[target.topic_id]

        if wrong_texts:
            query_text = f"{target_topic_obj.title}. " + ". ".join(wrong_texts)
            wrong_included = True
        else:
            query_text = target_topic_obj.title
            wrong_included = False

        query_vec = active_embedder.embed([query_text])[0]

        # Fetch candidate resources with cosine distance
        candidate_rows = (
            db.query(
                LearningResource,
                LearningResource.embedding.cosine_distance(query_vec).label("distance")
            )
            .filter(
                LearningResource.topic_id == target.topic_id,
                LearningResource.embedding.isnot(None)
            )
            .all()
        )

        if not candidate_rows:
            continue

        # Difficulty filter (with relaxation fallback)
        filtered_pairs = difficulty_filter(
            candidate_rows,
            target_rank=t_rank,
            rank_fn=lambda pair: difficulty_rank(pair[0].difficulty)
        )

        raw_cosines = [max(0.0, 1.0 - dist) for _, dist in filtered_pairs]
        scaled_semantics = minmax_scale(raw_cosines)

        cand_ids = [res.id for res, _ in filtered_pairs]
        all_candidate_resource_ids.extend(cand_ids)

        topic_data.append({
            "target": target,
            "target_rank": t_rank,
            "target_diff_str": t_diff_str,
            "wrong_included": wrong_included,
            "filtered_pairs": filtered_pairs,
            "scaled_semantics": scaled_semantics,
            "cand_ids": cand_ids,
        })

    # 8. Evaluate Collaborative Scores & Global Availability (Section 8.2)
    collab_scores: dict[int, float] = {}
    collab_improved_counts: dict[int, int] = {}

    if neighbours and all_candidate_resource_ids:
        collab_scores = collaborative_scores(
            neighbours,
            credits,
            all_candidate_resource_ids
        )
        for r_id in all_candidate_resource_ids:
            collab_improved_counts[r_id] = sum(
                1 for nid, _ in neighbours if (nid, r_id) in credits
            )

    has_nonzero_collab = any(
        score > 0.0 for score in collab_scores.values()
    )

    if strategy == "hybrid" and has_nonzero_collab:
        collaborative_available = True
        available_components = {"need", "semantic", "difficulty", "collab"}
    else:
        collaborative_available = False
        available_components = {"need", "semantic", "difficulty"}

    effective_weights = normalise_weights(base_weights, available_components)

    # 9. Multi-Component Scoring and Item Assembly
    all_selected_items: list[RecommendationItem] = []

    for t_info in topic_data:
        target = t_info["target"]
        t_rank = t_info["target_rank"]
        t_diff_str = t_info["target_diff_str"]
        wrong_included = t_info["wrong_included"]
        filtered_pairs = t_info["filtered_pairs"]
        scaled_semantics = t_info["scaled_semantics"]

        topic_scored_items: list[RecommendationItem] = []
        for (res, _), sem in zip(filtered_pairs, scaled_semantics):
            r_rank = difficulty_rank(res.difficulty)
            diff_fit_score = difficulty_fit(r_rank, t_rank)
            collab_val = collab_scores.get(res.id, 0.0) if collaborative_available else 0.0

            components = {
                "need": target.need,
                "semantic": sem,
                "difficulty": diff_fit_score,
                "collab": collab_val,
            }

            final_score = hybrid_score(components, effective_weights)
            n_improved = collab_improved_counts.get(res.id, 0)
            redirected_title = (
                topic_map[target.redirected_from].title
                if target.redirected_from
                else None
            )

            reason_str = build_reason(
                topic_title=topic_map[target.topic_id].title,
                target_kind=target.kind,
                mastery=target.mastery,
                resource_difficulty=res.difficulty,
                target_difficulty=t_diff_str,
                semantic_score=sem,
                wrong_answers_included=wrong_included,
                n_improved_peers=n_improved,
                redirected_from_title=redirected_title,
            )

            item = RecommendationItem(
                resource_id=res.id,
                topic_id=res.topic_id,
                score=final_score,
                rank=0,  # Assigned after sorting
                components={
                    "need": round(target.need, 4),
                    "semantic": round(sem, 4),
                    "difficulty_fit": round(diff_fit_score, 4),
                    "collaborative": round(collab_val, 4),
                },
                reason=reason_str,
                resource=res,
                target_topic_id=target.topic_id,
                target_kind=target.kind,
                redirected_from_topic_id=target.redirected_from,
                mastery=round(target.mastery, 4) if target.status != STATUS_NOT_ATTEMPTED else None,
                status=target.status,
            )
            topic_scored_items.append(item)

        # Sort descending by score, take top RESOURCES_PER_TOPIC (3)
        topic_scored_items.sort(key=lambda it: it.score, reverse=True)
        all_selected_items.extend(topic_scored_items[:RESOURCES_PER_TOPIC])

    # Assign sequential ranks across output items
    for idx, item in enumerate(all_selected_items, start=1):
        item.rank = idx

    return RecommendationResult(
        strategy=strategy,
        collaborative_available=collaborative_available,
        items=all_selected_items
    )

