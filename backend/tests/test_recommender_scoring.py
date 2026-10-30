"""Pure unit tests for recommender scoring, filtering, similarity, and target selection.

Zero database dependencies. Covers docs/RECOMMENDER.md Sections 4-11 and Chunk 6.4 (a), (b), (c).
"""

import pytest

from app.recommender.config import (
    K_NEIGHBORS,
    MAX_TARGET_TOPICS,
    MIN_SHARED_TOPICS,
    MIN_SIMILARITY,
    NOT_ATTEMPTED_NEED,
    STATUS_DEVELOPING,
    STATUS_NOT_ATTEMPTED,
    STATUS_STRONG,
    STATUS_WEAK,
    STRATEGIES,
)
from app.recommender.scoring import (
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
    similarity,
)


# ============================================================================
# (a) Section 10 Worked Example Benchmark & Core Math
# ============================================================================

def test_section_10_worked_example_hybrid_and_collaborative_unavailable():
    """Validates the exact numerical benchmark from docs/RECOMMENDER.md Section 10.

    Context:
    - Current Topic Mastery: p = 0.30 -> need = 0.70
    - Target Difficulty: p < 0.40 -> easy (rank 0)
    - Candidates:
        A: easy (0), raw cosine 0.62, collab 0.60
        B: medium (1), raw cosine 0.48, collab 0.10
        D: easy (0), raw cosine 0.40, collab 0.00
    """
    # 1. Target difficulty & need
    target_rank = difficulty_target(0.30)
    assert target_rank == 0  # easy
    need = 1.0 - 0.30
    assert need == 0.70

    # 2. Semantic min-max scaling across candidate cosines [0.62, 0.48, 0.40]
    scaled_sem = minmax_scale([0.62, 0.48, 0.40])
    # A: (0.62 - 0.40)/0.22 = 1.000
    assert pytest.approx(scaled_sem[0], 0.001) == 1.000
    # B: (0.48 - 0.40)/0.22 = 4/11 ≈ 0.3636 -> 0.364
    assert round(scaled_sem[1], 3) == 0.364
    # D: (0.40 - 0.40)/0.22 = 0.000
    assert pytest.approx(scaled_sem[2], 0.001) == 0.000

    # 3. Difficulty fit scores
    fit_A = difficulty_fit(difficulty_rank("easy"), target_rank)    # dist 0 -> 1.0
    fit_B = difficulty_fit(difficulty_rank("medium"), target_rank)  # dist 1 -> 0.5
    fit_D = difficulty_fit(difficulty_rank("easy"), target_rank)    # dist 0 -> 1.0
    assert fit_A == 1.0
    assert fit_B == 0.5
    assert fit_D == 1.0

    # 4. Case 1: Hybrid Strategy (All components available)
    # Weights: need=0.30, semantic=0.30, diff=0.15, collab=0.25
    hybrid_weights = STRATEGIES["hybrid"]
    all_available = {"need", "semantic", "difficulty", "collab"}

    comp_A = {"need": need, "semantic": scaled_sem[0], "difficulty": fit_A, "collab": 0.60}
    comp_B = {"need": need, "semantic": scaled_sem[1], "difficulty": fit_B, "collab": 0.10}
    comp_D = {"need": need, "semantic": scaled_sem[2], "difficulty": fit_D, "collab": 0.00}

    score_A_hybrid = hybrid_score(comp_A, hybrid_weights, all_available)
    score_B_hybrid = hybrid_score(comp_B, hybrid_weights, all_available)
    score_D_hybrid = hybrid_score(comp_D, hybrid_weights, all_available)

    # Benchmark assertions to 3 decimal places (Section 10)
    assert pytest.approx(0.810, abs=0.001) == score_A_hybrid
    assert pytest.approx(0.419, abs=0.001) == score_B_hybrid
    assert pytest.approx(0.360, abs=0.001) == score_D_hybrid

    # 5. Case 2: Collaborative Component Unavailable
    # Rescaled weights: need=0.40, semantic=0.40, diff=0.20, collab=0.00
    no_collab = {"need", "semantic", "difficulty"}

    score_A_no_collab = hybrid_score(comp_A, hybrid_weights, no_collab)
    score_B_no_collab = hybrid_score(comp_B, hybrid_weights, no_collab)
    score_D_no_collab = hybrid_score(comp_D, hybrid_weights, no_collab)

    # Benchmark assertions to 3 decimal places (Section 10)
    assert pytest.approx(0.880, abs=0.001) == score_A_no_collab
    assert pytest.approx(0.526, abs=0.001) == score_B_no_collab
    assert pytest.approx(0.480, abs=0.001) == score_D_no_collab


def test_normalise_weights_sum_to_one():
    """Normalized weights across available components must sum strictly to 1.0."""
    # Hybrid with all 4 components
    h_norm = normalise_weights(STRATEGIES["hybrid"], {"need", "semantic", "difficulty", "collab"})
    assert pytest.approx(sum(h_norm.values()), 1e-9) == 1.0
    assert h_norm["need"] == 0.30
    assert h_norm["collab"] == 0.25

    # Hybrid without collab
    h_no_collab = normalise_weights(STRATEGIES["hybrid"], {"need", "semantic", "difficulty"})
    assert pytest.approx(sum(h_no_collab.values()), 1e-9) == 1.0
    assert pytest.approx(h_no_collab["need"], 1e-9) == 0.40
    assert pytest.approx(h_no_collab["semantic"], 1e-9) == 0.40
    assert pytest.approx(h_no_collab["difficulty"], 1e-9) == 0.20

    # Content-only strategy
    c_norm = normalise_weights(STRATEGIES["content_only"], {"need", "semantic", "difficulty"})
    assert pytest.approx(sum(c_norm.values()), 1e-9) == 1.0
    assert c_norm["need"] == 0.40
    assert c_norm["difficulty"] == 0.20


def test_difficulty_filter_and_relaxation():
    """Excludes candidates with rank distance >= 2, relaxing if pool is left empty."""
    target_rank = 0  # easy

    pool = [
        {"id": 1, "difficulty": "easy"},    # rank 0: 0 - 0 = 0 < 2
        {"id": 2, "difficulty": "medium"},  # rank 1: 1 - 0 = 1 < 2
        {"id": 3, "difficulty": "hard"},    # rank 2: 2 - 0 = 2 >= 2 -> EXCLUDED
    ]
    filtered = difficulty_filter(pool, target_rank)
    assert len(filtered) == 2
    assert [r["id"] for r in filtered] == [1, 2]

    # Relaxation case: only hard resources exist for an easy-targeted learner
    hard_only_pool = [
        {"id": 3, "difficulty": "hard"},
        {"id": 4, "difficulty": "hard"},
    ]
    relaxed = difficulty_filter(hard_only_pool, target_rank)
    assert len(relaxed) == 2  # Returns all candidates when filter would eliminate all


def test_minmax_scale_edge_cases():
    """Edge cases: empty list, single item, all equal items."""
    assert minmax_scale([]) == []
    assert minmax_scale([0.75]) == [0.50]
    assert minmax_scale([0.42, 0.42, 0.42]) == [0.50, 0.50, 0.50]


# ============================================================================
# (b) Similarity, Neighbors, Credits, Collaborative Formula
# ============================================================================

def test_similarity_shared_topics_and_threshold():
    """Similarity requires at least MIN_SHARED_TOPICS (3); otherwise returns None."""
    # Only 2 shared topics -> returns None
    u = {1: 0.80, 2: 0.70}
    v = {1: 0.85, 2: 0.65}
    assert similarity(u, v) is None

    # 3 shared topics with identical mastery -> 1.0
    u_ident = {1: 0.80, 2: 0.70, 3: 0.50}
    v_ident = {1: 0.80, 2: 0.70, 3: 0.50}
    assert similarity(u_ident, v_ident) == 1.0

    # 3 shared topics with known delta: |0.8-0.9|=0.1, |0.7-0.7|=0, |0.5-0.3|=0.2
    # mean delta = (0.1 + 0.0 + 0.2) / 3 = 0.10 -> sim = 1.0 - 0.10 = 0.90
    v_diff = {1: 0.90, 2: 0.70, 3: 0.30}
    assert pytest.approx(similarity(u_ident, v_diff), 1e-9) == 0.90


def test_pick_neighbours_thresholds_and_self_exclusion():
    """Excludes self, enforces MIN_SIMILARITY (0.75), and limits to K_NEIGHBORS (10)."""
    target_id = 1
    learners = {
        1: {1: 0.8, 2: 0.8, 3: 0.8},
        2: {1: 0.8, 2: 0.8, 3: 0.8},    # sim = 1.00
        3: {1: 0.6, 2: 0.6, 3: 0.6},    # delta=0.20 -> sim = 0.80
        4: {1: 0.1, 2: 0.1, 3: 0.1},    # delta=0.70 -> sim = 0.30 (< 0.75, excluded)
    }
    neighbours = pick_neighbours(target_id, learners, min_similarity=MIN_SIMILARITY, k=K_NEIGHBORS)
    assert len(neighbours) == 2
    # Target self (1) excluded
    assert not any(nid == 1 for nid, _ in neighbours)
    assert neighbours[0] == (2, 1.0)
    assert pytest.approx(neighbours[1][1], 1e-9) == 0.80


def test_collaborative_scores_calculation():
    """Hand-computed collaborative score verification."""
    # Neighbors: peer 2 (sim=0.8), peer 3 (sim=0.6). Total sim = 1.4
    neighbours = [(2, 0.8), (3, 0.6)]
    # Credits: peer 2 clicked and improved on res 101. peer 3 did not.
    credits = {(2, 101): 1, (3, 102): 1}

    scores = collaborative_scores(neighbours, credits, [101, 102, 103])
    # 101: (0.8 * 1 + 0.6 * 0) / 1.4 = 0.8 / 1.4 = 4/7 ≈ 0.5714
    assert pytest.approx(scores[101], 0.001) == 0.5714
    # 102: (0.8 * 0 + 0.6 * 1) / 1.4 = 0.6 / 1.4 = 3/7 ≈ 0.4286
    assert pytest.approx(scores[102], 0.001) == 0.4286
    # 103: (0 + 0) / 1.4 = 0.0
    assert scores[103] == 0.0


# ============================================================================
# (c) select_targets: Substitution, Cycles, Backfill
# ============================================================================

def test_select_targets_weak_prerequisite_substitution():
    """Weak topic is substituted by its weak prerequisite."""
    # Topic 2 (OSI) is weak, but requires Topic 1 (Network Fund) which is also weak
    statuses = {1: STATUS_WEAK, 2: STATUS_WEAK}
    mastery = {1: 0.20, 2: 0.35}
    prerequisites = {2: [1]}
    topic_order = [1, 2]
    has_res = {1, 2}

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) == 1
    # Topic 1 was substituted in place of Topic 2
    assert targets[0].topic_id == 1
    assert targets[0].redirected_from == 2


def test_select_targets_chain_of_two_weak_prerequisites():
    """Recursively walks a chain of two weak prerequisites."""
    # Topic 3 -> Topic 2 -> Topic 1 (all weak)
    statuses = {1: STATUS_WEAK, 2: STATUS_WEAK, 3: STATUS_WEAK}
    mastery = {1: 0.15, 2: 0.25, 3: 0.35}
    prerequisites = {3: [2], 2: [1]}
    topic_order = [1, 2, 3]
    has_res = {1, 2, 3}

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) == 1
    assert targets[0].topic_id == 1
    assert targets[0].redirected_from == 3


def test_select_targets_prerequisite_cycle_does_not_loop_forever():
    """A cycle in prerequisites is halted cleanly by the visited-set guard."""
    statuses = {1: STATUS_WEAK, 2: STATUS_WEAK}
    mastery = {1: 0.20, 2: 0.20}
    prerequisites = {1: [2], 2: [1]}  # Cycle
    topic_order = [1, 2]
    has_res = {1, 2}

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) >= 1  # Successfully terminates without RecursionError / Timeout


def test_select_targets_fill_rule_for_brand_new_learner():
    """Brand new learner gets up to 3 unattempted topics where all prereqs are satisfied/empty."""
    statuses = {1: STATUS_NOT_ATTEMPTED, 2: STATUS_NOT_ATTEMPTED, 3: STATUS_NOT_ATTEMPTED, 4: STATUS_NOT_ATTEMPTED}
    mastery = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    # 1 has no prereq (eligible)
    # 2 requires 1 (ineligible because 1 is not strong)
    # 3 has no prereq (eligible)
    # 4 has no prereq (eligible)
    prerequisites = {2: [1]}
    topic_order = [1, 2, 3, 4]
    has_res = {1, 2, 3, 4}

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) == 3
    assert [t.topic_id for t in targets] == [1, 3, 4]
    for t in targets:
        assert t.kind == "start_here"
        assert t.need == NOT_ATTEMPTED_NEED


def test_select_targets_skips_topics_without_embedded_resources():
    """Topics containing zero embedded learning resources are skipped."""
    statuses = {1: STATUS_WEAK, 2: STATUS_WEAK}
    mastery = {1: 0.10, 2: 0.20}
    prerequisites = {}
    topic_order = [1, 2]
    # Topic 1 has NO embedded resources
    has_res = {2}

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) == 1
    assert targets[0].topic_id == 2


def test_select_targets_never_exceeds_max_targets():
    """Never returns more than MAX_TARGET_TOPICS (3) topics."""
    statuses = {i: STATUS_WEAK for i in range(1, 10)}
    mastery = {i: 0.10 for i in range(1, 10)}
    prerequisites = {}
    topic_order = list(range(1, 10))
    has_res = set(range(1, 10))

    targets = select_targets(statuses, mastery, prerequisites, topic_order, has_res)
    assert len(targets) == MAX_TARGET_TOPICS
