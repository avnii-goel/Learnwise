"""Unit tests for the pure adaptive quizzing question selection engine.

Reference: docs/ADAPTIVE_QUIZ.md Sections 3, 4, 5.
Pure unit tests: Zero database access, deterministic RNG fixtures.
"""

from datetime import datetime, timezone, timedelta
import random
import pytest

from app.services.adaptive import (
    ADAPTIVE_QUIZ_LENGTH,
    SELECTION_UNSEEN_AT_TARGET,
    SELECTION_UNSEEN_OTHER_LEVEL,
    SELECTION_SEEN_REUSED,
    advance_running_mastery,
    choose_next_question,
    target_difficulty,
    target_difficulty_rank,
)


@pytest.fixture
def question_pool():
    """Generates a rich fixture pool of at least 8 questions per difficulty level."""
    pool = []
    # 10 Easy questions (IDs 1-10)
    for i in range(1, 11):
        pool.append({
            "id": i,
            "topic_id": 1,
            "question_text": f"Easy question {i}",
            "difficulty": "easy",
        })
    # 10 Medium questions (IDs 11-20)
    for i in range(11, 21):
        pool.append({
            "id": i,
            "topic_id": 1,
            "question_text": f"Medium question {i}",
            "difficulty": "medium",
        })
    # 10 Hard questions (IDs 21-30)
    for i in range(21, 31):
        pool.append({
            "id": i,
            "topic_id": 1,
            "question_text": f"Hard question {i}",
            "difficulty": "hard",
        })
    return pool


def test_section_4_worked_example_trace():
    """Validates Section 4 worked example traces computed through the real update_mastery."""
    # --- Trace 1 (Start p = 0.50) ---
    p = 0.50
    assert target_difficulty(p) == "medium"

    # Q1 Medium Correct: 0.50 -> 0.8043 (next Hard)
    p = advance_running_mastery(p, True, "medium")
    assert round(p, 4) == 0.8043
    assert target_difficulty(p) == "hard"

    # Q2 Hard Correct: 0.8043 -> 0.9513 (next Hard)
    p = advance_running_mastery(p, True, "hard")
    assert round(p, 4) == 0.9513
    assert target_difficulty(p) == "hard"

    # Q3 Hard Wrong: 0.9513 -> 0.8069 (next Hard)
    p = advance_running_mastery(p, False, "hard")
    assert round(p, 4) == 0.8069
    assert target_difficulty(p) == "hard"

    # Q4 Hard Wrong: 0.8069 -> 0.4954 (next Medium)
    p = advance_running_mastery(p, False, "hard")
    assert round(p, 4) == 0.4954
    assert target_difficulty(p) == "medium"

    # --- Trace 2 (Cold start p = 0.30 rapid progression) ---
    p_cold = 0.30
    assert target_difficulty(p_cold) == "easy"

    p_cold = advance_running_mastery(p_cold, True, "easy")
    assert round(p_cold, 4) == 0.6182
    assert target_difficulty(p_cold) == "medium"

    p_cold = advance_running_mastery(p_cold, True, "medium")
    assert round(p_cold, 4) == 0.8682
    assert target_difficulty(p_cold) == "hard"

    # --- Trace 3 (Cold start p = 0.30 repeated errors) ---
    p_err = 0.30
    assert target_difficulty(p_err) == "easy"

    p_err = advance_running_mastery(p_err, False, "easy")
    assert round(p_err, 4) == 0.1267
    assert target_difficulty(p_err) == "easy"

    p_err = advance_running_mastery(p_err, False, "easy")
    assert round(p_err, 4) == 0.1092
    assert target_difficulty(p_err) == "easy"


def test_cold_start_initial_target():
    """Unattempted or low mastery values initialize strictly at Easy difficulty."""
    assert target_difficulty(None) == "easy"
    assert target_difficulty(0.30) == "easy"
    assert target_difficulty(0.0) == "easy"
    assert target_difficulty(0.3999) == "easy"
    assert target_difficulty_rank(0.30) == 0

    assert target_difficulty(0.40) == "medium"
    assert target_difficulty(0.6999) == "medium"
    assert target_difficulty_rank(0.50) == 1

    assert target_difficulty(0.70) == "hard"
    assert target_difficulty(0.95) == "hard"
    assert target_difficulty_rank(0.85) == 2


def test_simulated_good_learner_difficulty_trends_up(question_pool):
    """A simulated good learner (100% correct) over 8 questions escalates and never decreases difficulty."""
    rng = random.Random(42)
    p = 0.30  # Cold start
    served_difficulties = []
    served_ids = set()

    for step in range(ADAPTIVE_QUIZ_LENGTH):
        target = target_difficulty(p)
        available_candidates = [q for q in question_pool if q["id"] not in served_ids]

        res = choose_next_question(
            candidates=available_candidates,
            target=target,
            seen_ids=served_ids,
            rng=rng,
        )
        chosen = res.question
        served_ids.add(chosen["id"])
        served_difficulties.append(chosen["difficulty"])

        # Good learner always answers correctly
        p = advance_running_mastery(p, True, chosen["difficulty"])

    assert len(served_difficulties) == 8
    assert len(served_ids) == 8
    # Progression: step 0 easy -> step 1 medium -> steps 2..7 hard
    assert served_difficulties[0] == "easy"
    assert served_difficulties[1] == "medium"
    for diff in served_difficulties[2:]:
        assert diff == "hard"

    # Verify difficulty never decreases
    rank_map = {"easy": 0, "medium": 1, "hard": 2}
    ranks = [rank_map[d] for d in served_difficulties]
    for i in range(len(ranks) - 1):
        assert ranks[i + 1] >= ranks[i]


def test_simulated_bad_learner_stays_easy(question_pool):
    """A simulated struggling learner (0% correct) stays locked at Easy difficulty for all 8 questions."""
    rng = random.Random(42)
    p = 0.30  # Cold start
    served_difficulties = []
    served_ids = set()

    for step in range(ADAPTIVE_QUIZ_LENGTH):
        target = target_difficulty(p)
        available_candidates = [q for q in question_pool if q["id"] not in served_ids]

        res = choose_next_question(
            candidates=available_candidates,
            target=target,
            seen_ids=served_ids,
            rng=rng,
        )
        chosen = res.question
        served_ids.add(chosen["id"])
        served_difficulties.append(chosen["difficulty"])

        # Bad learner always answers incorrectly
        p = advance_running_mastery(p, False, chosen["difficulty"])

    assert len(served_difficulties) == 8
    assert len(served_ids) == 8
    # All 8 questions served must be easy
    for diff in served_difficulties:
        assert diff == "easy"


def test_simulated_mixed_learner_follows_worked_example(question_pool):
    """A learner responding to the worked example pattern transitions appropriately."""
    rng = random.Random(42)
    p = 0.50  # Start at medium
    served_ids = set()
    steps_history = []

    # Sequence: Correct, Correct, Wrong, Wrong
    answers = [True, True, False, False]

    for is_correct in answers:
        target = target_difficulty(p)
        available_candidates = [q for q in question_pool if q["id"] not in served_ids]

        res = choose_next_question(
            candidates=available_candidates,
            target=target,
            seen_ids=served_ids,
            rng=rng,
        )
        chosen = res.question
        served_ids.add(chosen["id"])
        steps_history.append((chosen["difficulty"], target))

        p = advance_running_mastery(p, is_correct, chosen["difficulty"])

    # Q1: Target Medium, answered Correct -> next Target Hard
    assert steps_history[0] == ("medium", "medium")
    # Q2: Target Hard, answered Correct -> next Target Hard
    assert steps_history[1] == ("hard", "hard")
    # Q3: Target Hard, answered Wrong -> next Target Hard
    assert steps_history[2] == ("hard", "hard")
    # Q4: Target Hard, answered Wrong -> next Target Medium
    assert steps_history[3] == ("hard", "hard")
    assert target_difficulty(p) == "medium"


def test_no_question_repeats_within_one_quiz(question_pool):
    """Questions served in earlier steps of the same attempt are strictly excluded."""
    rng = random.Random(99)
    served_ids = set()
    p = 0.40

    for _ in range(ADAPTIVE_QUIZ_LENGTH):
        available = [q for q in question_pool if q["id"] not in served_ids]
        res = choose_next_question(
            candidates=available,
            target=target_difficulty(p),
            seen_ids=served_ids,
            rng=rng,
        )
        assert res.question["id"] not in served_ids
        served_ids.add(res.question["id"])
        p = advance_running_mastery(p, True, res.question["difficulty"])

    assert len(served_ids) == ADAPTIVE_QUIZ_LENGTH


def test_cost_rule_unseen_medium_beats_seen_hard_tie():
    """Unseen medium (|1-2|+0=1) beats seen hard (|2-2|+1=1) on tie-breaker criterion 1 (Unseen First)."""
    candidates = [
        {"id": 101, "difficulty": "medium"},  # Unseen medium: cost = 1
        {"id": 102, "difficulty": "hard"},    # Seen hard: cost = 1
    ]
    seen_ids = {102}

    res = choose_next_question(
        candidates=candidates,
        target="hard",
        seen_ids=seen_ids,
    )
    assert res.question["id"] == 101
    assert res.selection_reason == SELECTION_UNSEEN_OTHER_LEVEL


def test_cost_rule_unseen_easy_at_distance_2_loses_to_seen_hard():
    """Unseen easy at distance 2 (|0-2|+0=2) loses to seen hard (|2-2|+1=1) on lower cost."""
    candidates = [
        {"id": 201, "difficulty": "easy"},  # Unseen easy: cost = 2
        {"id": 202, "difficulty": "hard"},  # Seen hard: cost = 1
    ]
    seen_ids = {202}

    res = choose_next_question(
        candidates=candidates,
        target="hard",
        seen_ids=seen_ids,
    )
    assert res.question["id"] == 202
    assert res.selection_reason == SELECTION_SEEN_REUSED


def test_fallback_when_difficulty_level_is_exhausted():
    """When the target difficulty pool is empty, the engine falls back to the nearest level."""
    # Target is hard, but candidate pool only has Medium and Easy
    candidates = [
        {"id": 301, "difficulty": "easy"},    # cost = |0-2| + 0 = 2
        {"id": 302, "difficulty": "medium"},  # cost = |1-2| + 0 = 1
    ]

    res = choose_next_question(
        candidates=candidates,
        target="hard",
        seen_ids=set(),
    )
    assert res.question["id"] == 302
    assert res.selection_reason == SELECTION_UNSEEN_OTHER_LEVEL


def test_tie_breaking_order_hierarchy():
    """Validates the full tie-breaking hierarchy: unseen first -> easier level -> oldest seen -> RNG."""
    # Criterion 1: Unseen beats seen (already tested above)

    # Criterion 2: Both unseen, same cost -> Easier level wins (lower rank)
    # Target = Medium (rank 1).
    # Easy (rank 0): cost |0-1| + 0 = 1
    # Hard (rank 2): cost |2-1| + 0 = 1
    candidates_diff = [
        {"id": 401, "difficulty": "hard"},
        {"id": 402, "difficulty": "easy"},
    ]
    res_diff = choose_next_question(
        candidates=candidates_diff,
        target="medium",
        seen_ids=set(),
    )
    assert res_diff.question["id"] == 402  # Easy (rank 0) beats Hard (rank 2)
    assert res_diff.selection_reason == SELECTION_UNSEEN_OTHER_LEVEL

    # Criterion 3: Both seen, same cost and rank -> Least recently answered (oldest timestamp) wins
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=10)
    recent_time = now - timedelta(days=1)

    candidates_seen = [
        {"id": 501, "difficulty": "hard"},  # recent
        {"id": 502, "difficulty": "hard"},  # older
    ]
    last_seen_at = {
        501: recent_time,
        502: old_time,
    }
    res_seen = choose_next_question(
        candidates=candidates_seen,
        target="hard",
        seen_ids={501, 502},
        last_seen_at=last_seen_at,
    )
    assert res_seen.question["id"] == 502  # Older timestamp wins
    assert res_seen.selection_reason == SELECTION_SEEN_REUSED

    # Criterion 4: Exact tie broken deterministically by seeded RNG
    candidates_exact = [
        {"id": 601, "difficulty": "medium"},
        {"id": 602, "difficulty": "medium"},
    ]
    # Deterministic choice with fixed seed
    rng1 = random.Random(1234)
    res_rng1 = choose_next_question(candidates_exact, target="medium", rng=rng1)
    rng2 = random.Random(1234)
    res_rng2 = choose_next_question(candidates_exact, target="medium", rng=rng2)
    assert res_rng1.question["id"] == res_rng2.question["id"]

