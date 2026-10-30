"""Pure scoring, ranking, neighbor filtering, and explanation functions.

Zero database or ORM imports. Pure mathematical and algorithmic module.
Reference: docs/RECOMMENDER.md Sections 4-11.
"""

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.recommender.config import (
    DIFFICULTY_RANKS,
    DIFFICULTY_TARGET_EASY_MAX,
    DIFFICULTY_TARGET_MEDIUM_MAX,
    IMPROVEMENT_MARGIN,
    K_NEIGHBORS,
    MAX_TARGET_TOPICS,
    MIN_SHARED_TOPICS,
    MIN_SIMILARITY,
    NOT_ATTEMPTED_NEED,
    STATUS_DEVELOPING,
    STATUS_NOT_ATTEMPTED,
    STATUS_STRONG,
    STATUS_WEAK,
)


# ============================================================================
# 1. Difficulty Functions (Section 6 & 9.1)
# ============================================================================

def difficulty_rank(label: str | None) -> int:
    """Maps difficulty string ('easy', 'medium', 'hard') to integer rank (0, 1, 2).

    Defaults to medium (1) for unknown or None values.
    """
    if not label:
        return 1
    return DIFFICULTY_RANKS.get(label.strip().lower(), 1)


def difficulty_target(mastery: float | None) -> int:
    """Computes target difficulty rank (0, 1, 2) from current topic mastery.

    - Easy (0): mastery < 0.40 (or unattempted / None)
    - Medium (1): 0.40 <= mastery < 0.70
    - Hard (2): mastery >= 0.70
    """
    if mastery is None or mastery < DIFFICULTY_TARGET_EASY_MAX:
        return 0
    if mastery < DIFFICULTY_TARGET_MEDIUM_MAX:
        return 1
    return 2


def difficulty_fit(resource_rank: int, target_rank: int) -> float:
    """Calculates difficulty fit score based on rank distance.

    - 0 levels apart: 1.0
    - 1 level apart: 0.5
    - 2 levels apart: 0.0
    """
    dist = abs(resource_rank - target_rank)
    if dist == 0:
        return 1.0
    if dist == 1:
        return 0.5
    return 0.0


def difficulty_filter(
    resources: Sequence[Any],
    target_rank: int,
    rank_fn: Callable[[Any], int] | None = None
) -> list[Any]:
    """Excludes candidates where (resource_rank - target_rank >= 2).

    If filtering eliminates all candidate resources for this topic, relaxes
    the filter and returns the original pool (relaxation rule, Section 6.2).
    """
    if not resources:
        return []

    def _get_rank(item: Any) -> int:
        if rank_fn is not None:
            return rank_fn(item)
        if isinstance(item, dict):
            return difficulty_rank(item.get("difficulty"))
        if hasattr(item, "difficulty"):
            return difficulty_rank(getattr(item, "difficulty"))
        if isinstance(item, int):
            return item
        return 1

    filtered = [r for r in resources if _get_rank(r) - target_rank < 2]
    if not filtered:
        # Filter relaxation rule: return all candidates
        return list(resources)
    return filtered


# ============================================================================
# 2. Scaling & Weight Normalization (Section 9)
# ============================================================================

def minmax_scale(values: Sequence[float]) -> list[float]:
    """Min-max scales values to [0.0, 1.0] across candidates within a topic pool.

    If pool size is 1 or all values are identical, defaults each to 0.50 (Section 9.1).
    """
    if not values:
        return []
    if len(values) == 1:
        return [0.50]

    min_val = min(values)
    max_val = max(values)
    span = max_val - min_val

    if span == 0.0:
        return [0.50] * len(values)

    return [(v - min_val) / span for v in values]


def normalise_weights(
    weights: dict[str, float],
    available_components: set[str]
) -> dict[str, float]:
    """Dynamically drops unavailable or zero-weight components and renormalizes sum to 1.0."""
    active = {
        k: w for k, w in weights.items()
        if k in available_components and w > 0.0
    }
    total = sum(active.values())
    if total <= 0.0:
        return {}
    return {k: w / total for k, w in active.items()}


def hybrid_score(
    components: dict[str, float],
    weights: dict[str, float],
    available: set[str] | None = None
) -> float:
    """Calculates weighted linear combination score.

    Renormalizes weights over available components if available set is provided.
    """
    if available is not None:
        effective_weights = normalise_weights(weights, available)
    else:
        effective_weights = weights

    return sum(
        effective_weights.get(k, 0.0) * components.get(k, 0.0)
        for k in effective_weights
    )


# ============================================================================
# 3. Learner Similarity & Collaborative Filtering (Sections 7 & 8)
# ============================================================================

def similarity(m_u: dict[int, float], m_v: dict[int, float]) -> float | None:
    """Computes similarity between learner u and peer v across shared attempted topics.

    sim(u, v) = 1.0 - (1 / |S_uv|) * sum(|m_u,t - m_v,t|)
    Returns None if |S_uv| < MIN_SHARED_TOPICS (3).
    """
    shared = set(m_u.keys()) & set(m_v.keys())
    if len(shared) < MIN_SHARED_TOPICS:
        return None

    diff_sum = sum(abs(m_u[t] - m_v[t]) for t in shared)
    return 1.0 - (diff_sum / len(shared))


def pick_neighbours(
    target_user_id: int,
    all_learners_mastery: dict[int, dict[int, float]],
    min_similarity: float = MIN_SIMILARITY,
    k: int = K_NEIGHBORS
) -> list[tuple[int, float]]:
    """Selects top K most similar peers meeting the correlation threshold.

    Strictly excludes target_user_id. Sorts descending by similarity with stable
    tie-breaking by peer ID ascending.
    """
    target_mastery = all_learners_mastery.get(target_user_id, {})
    if not target_mastery:
        return []

    candidates: list[tuple[int, float]] = []
    for peer_id, peer_mastery in all_learners_mastery.items():
        if peer_id == target_user_id:
            continue
        sim = similarity(target_mastery, peer_mastery)
        if sim is not None and sim >= min_similarity:
            candidates.append((peer_id, sim))

    # Sort descending by sim, ascending by peer_id
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return candidates[:k]


def collaborative_scores(
    neighbours: list[tuple[int, float]],
    credits: dict[tuple[int, int], int],
    candidate_resource_ids: Sequence[int]
) -> dict[int, float]:
    """Computes collaborative score for candidate resources across the peer neighborhood.

    collab(r) = sum(sim * credit) / sum(sim)
    Each (neighbour, resource) pair is credited at most once.
    """
    total_sim = sum(sim for _, sim in neighbours)
    if total_sim <= 0.0 or not neighbours:
        return {r_id: 0.0 for r_id in candidate_resource_ids}

    scores: dict[int, float] = {}
    for r_id in candidate_resource_ids:
        numerator = sum(
            sim * credits.get((v, r_id), 0)
            for v, sim in neighbours
        )
        scores[r_id] = numerator / total_sim

    return scores


# ============================================================================
# 4. Target Topic Selection & Prerequisite Substitution (Sections 4 & 5)
# ============================================================================

@dataclass
class TargetTopic:
    topic_id: int
    need: float
    mastery: float
    status: str
    kind: str  # "weak", "developing", or "start_here"
    redirected_from: int | None = None


def select_targets(
    statuses: dict[int, str],
    mastery: dict[int, float],
    prerequisites: dict[int, list[int]],
    topic_order: list[int],
    has_resources: Callable[[int], bool] | set[int]
) -> list[TargetTopic]:
    """Selects up to MAX_TARGET_TOPICS (3) focus topics according to Sections 4 & 5:

    1. Weak & developing topics sorted by need (1.0 - mastery).
    2. Prerequisite substitution: If topic has a weak prerequisite, recursively
       substitute with the prerequisite until reaching one with no weak dependencies.
       Guarded by a visited set against cycles.
    3. Backfill with unattempted topics where all prerequisites are strong or non-existent,
       in course/topic sequence order, with need = NOT_ATTEMPTED_NEED (0.50).
    4. Guard: Skips any topic with zero embedded resources.
    """
    is_resource_available = (
        (lambda tid: tid in has_resources)
        if isinstance(has_resources, set)
        else has_resources
    )

    def _resolve_weak_prerequisites(tid: int) -> tuple[int, int | None]:
        curr = tid
        original = tid
        visited = {curr}
        while True:
            prereqs = prerequisites.get(curr, [])
            weak_prereqs = [
                p for p in prereqs
                if statuses.get(p) == STATUS_WEAK and p not in visited
            ]
            if not weak_prereqs:
                break
            # Follow weak prerequisite chain
            curr = weak_prereqs[0]
            visited.add(curr)

        redirected = original if curr != original else None
        return curr, redirected

    selected_targets: list[TargetTopic] = []
    seen_topic_ids: set[int] = set()
    order_map = {tid: idx for idx, tid in enumerate(topic_order)}

    # Step 1: Weak & Developing Candidates
    # Map resolved_id -> (need_val, status, redirected_from)
    resolved_map: dict[int, dict[str, Any]] = {}

    for tid, st in statuses.items():
        if st in (STATUS_WEAK, STATUS_DEVELOPING):
            resolved_id, redirected_from = _resolve_weak_prerequisites(tid)
            if not is_resource_available(resolved_id):
                continue

            m_val = mastery.get(resolved_id, 0.0)
            need_val = 1.0 - m_val
            target_status = statuses.get(resolved_id, st)

            if resolved_id not in resolved_map:
                resolved_map[resolved_id] = {
                    "need": need_val,
                    "status": target_status,
                    "redirected_from": redirected_from,
                }
            else:
                existing = resolved_map[resolved_id]
                # If current has a redirected_from and existing does not, or current is further down the chain
                if redirected_from is not None:
                    if existing["redirected_from"] is None:
                        existing["redirected_from"] = redirected_from
                    else:
                        # Prefer the one with higher order / deeper in topic order
                        curr_ord = order_map.get(redirected_from, -1)
                        prev_ord = order_map.get(existing["redirected_from"], -1)
                        if curr_ord > prev_ord:
                            existing["redirected_from"] = redirected_from

    attempted_candidates: list[tuple[int, float, str, int | None]] = [
        (tid, data["need"], data["status"], data["redirected_from"])
        for tid, data in resolved_map.items()
    ]

    # Sort descending by need, then earlier in topic_order for stable ties
    attempted_candidates.sort(
        key=lambda item: (-item[1], order_map.get(item[0], 999999))
    )

    for resolved_id, need_val, st, redirected_from in attempted_candidates:
        seen_topic_ids.add(resolved_id)
        kind = "weak" if st == STATUS_WEAK else "developing"
        selected_targets.append(
            TargetTopic(
                topic_id=resolved_id,
                need=need_val,
                mastery=mastery.get(resolved_id, 0.0),
                status=st,
                kind=kind,
                redirected_from=redirected_from,
            )
        )
        if len(selected_targets) >= MAX_TARGET_TOPICS:
            return selected_targets

    # Step 2: Backfill with Unattempted Topics (Section 5.2)
    for tid in topic_order:
        if len(selected_targets) >= MAX_TARGET_TOPICS:
            break
        if tid in seen_topic_ids:
            continue
        if statuses.get(tid) != STATUS_NOT_ATTEMPTED:
            continue
        if not is_resource_available(tid):
            continue

        # Eligibility: all prerequisites must be strong or non-existent
        prereqs = prerequisites.get(tid, [])
        all_strong = all(statuses.get(p) == STATUS_STRONG for p in prereqs)
        if not all_strong:
            continue

        seen_topic_ids.add(tid)
        selected_targets.append(
            TargetTopic(
                topic_id=tid,
                need=NOT_ATTEMPTED_NEED,
                mastery=0.0,
                status=STATUS_NOT_ATTEMPTED,
                kind="start_here",
                redirected_from=None,
            )
        )

    return selected_targets


# ============================================================================
# 5. Deterministic Explanation Engine (Section 11)
# ============================================================================

def build_reason(
    topic_title: str,
    target_kind: str,
    mastery: float,
    resource_difficulty: str,
    target_difficulty: str,
    semantic_score: float,
    wrong_answers_included: bool,
    n_improved_peers: int = 0,
    redirected_from_title: str | None = None,
) -> str:
    """Produces the deterministic explanation string adhering strictly to Section 11.

    Zero external LLM inference. Never includes peer names or emails.
    """
    clauses: list[str] = []
    pct = int(round(mastery * 100))

    # 1. Competency Status Clause
    if target_kind == "weak":
        clauses.append(f"Your mastery in {topic_title} is low ({pct}%).")
    elif target_kind == "developing":
        clauses.append(f"You are making progress in {topic_title} ({pct}% mastery).")
    elif target_kind == "start_here":
        clauses.append(f"You have not started {topic_title} yet.")

    # 2. Prerequisite Redirection Clause
    if redirected_from_title:
        clauses.append(
            f"You are weak in {topic_title}, a foundational prerequisite of {redirected_from_title}; focus on this first."
        )

    # 3. Misconception / Semantic Clause
    if semantic_score >= 0.50 and wrong_answers_included:
        clauses.append("Matches the questions you recently answered incorrectly in this topic.")

    # 4. Difficulty Alignment Clause
    r_rank = difficulty_rank(resource_difficulty)
    t_rank = difficulty_rank(target_difficulty)
    if r_rank == t_rank:
        clauses.append(f"Matches your recommended {target_difficulty.lower()} difficulty level.")
    elif abs(r_rank - t_rank) == 1:
        clauses.append("Introduces slightly more advanced material to challenge your understanding.")

    # 5. Peer Evidence Clause
    if n_improved_peers > 0:
        clauses.append(
            f"{n_improved_peers} similar learner(s) improved their mastery after engaging with this resource."
        )

    # 6. Unattempted Fill Clause
    if target_kind == "start_here":
        clauses.append("Topic not started, but all prerequisite competencies have been satisfied.")

    return " ".join(clauses)
