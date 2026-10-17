"""Unit tests for the pure Bayesian Knowledge Tracing (BKT) module.

Tests mathematical correctness, edge cases, clamping, order sensitivity,
difficulty normalization, and classification boundaries per docs/KNOWLEDGE_MODEL.md.
"""

import pytest

from app.config import bkt as bkt_config
from app.services.bkt import apply_answers, classify, update_mastery


def test_worked_examples():
    """Verifies the four reference worked examples from Section 3 within 1e-4 tolerance."""
    p_init = 0.30

    # 1. Medium question - Correct answer -> 0.6460
    p_med_correct = update_mastery(p_init, True, "medium")
    assert p_med_correct == pytest.approx(0.6460, abs=1e-4)

    # 2. Medium question - Wrong answer -> 0.1486
    p_med_wrong = update_mastery(p_init, False, "medium")
    assert p_med_wrong == pytest.approx(0.1486, abs=1e-4)

    # 3. Easy question - Correct answer -> 0.6182
    p_easy_correct = update_mastery(p_init, True, "easy")
    assert p_easy_correct == pytest.approx(0.6182, abs=1e-4)

    # 4. Hard question - Correct answer -> 0.6810
    p_hard_correct = update_mastery(p_init, True, "hard")
    assert p_hard_correct == pytest.approx(0.6810, abs=1e-4)


def test_correct_raises_and_wrong_lowers_mastery():
    """Verifies that correct answers increase mastery and wrong answers decrease mastery across all difficulties."""
    difficulties = ["easy", "medium", "hard"]
    starting_probs = [0.15, 0.30, 0.50, 0.75]

    for diff in difficulties:
        for p in starting_probs:
            p_up = update_mastery(p, True, diff)
            p_down = update_mastery(p, False, diff)
            assert p_up > p, f"Expected correct answer to increase mastery from {p} for {diff}"
            assert p_down < p, f"Expected wrong answer to decrease mastery from {p} for {diff}"


def test_difficulty_sensitivity():
    """Verifies that hard correct answers yield larger gains, and easy wrong answers yield larger penalties."""
    starting_probs = [0.30, 0.50, 0.70]

    for p in starting_probs:
        # Correct answer: Hard question gives more positive evidence than Easy question
        gain_hard = update_mastery(p, True, "hard") - p
        gain_easy = update_mastery(p, True, "easy") - p
        assert gain_hard > gain_easy, f"Hard gain ({gain_hard}) should exceed easy gain ({gain_easy}) at p={p}"

        # Wrong answer: Slipping on Easy question is stronger negative evidence than missing Hard question
        p_wrong_easy = update_mastery(p, False, "easy")
        p_wrong_hard = update_mastery(p, False, "hard")
        assert p_wrong_easy < p_wrong_hard, f"Wrong easy ({p_wrong_easy}) should drop lower than wrong hard ({p_wrong_hard}) at p={p}"


def test_probability_clamping_and_extreme_iterations():
    """Verifies that mastery strictly stays within [MIN_P, MAX_P], even after 200 consecutive correct or wrong answers."""
    # 200 consecutive wrong answers starting from MIN_P
    p_wrong_from_min = bkt_config.MIN_P
    for _ in range(200):
        p_wrong_from_min = update_mastery(p_wrong_from_min, False, "easy")
        assert bkt_config.MIN_P <= p_wrong_from_min <= bkt_config.MAX_P

    # 200 consecutive wrong answers starting from MAX_P
    p_wrong_from_max = bkt_config.MAX_P
    for _ in range(200):
        p_wrong_from_max = update_mastery(p_wrong_from_max, False, "medium")
        assert bkt_config.MIN_P <= p_wrong_from_max <= bkt_config.MAX_P

    # 200 consecutive correct answers starting from MIN_P
    p_correct_from_min = bkt_config.MIN_P
    for _ in range(200):
        p_correct_from_min = update_mastery(p_correct_from_min, True, "medium")
        assert bkt_config.MIN_P <= p_correct_from_min <= bkt_config.MAX_P
    assert p_correct_from_min == pytest.approx(bkt_config.MAX_P)

    # 200 consecutive correct answers starting from MAX_P
    p_correct_from_max = bkt_config.MAX_P
    for _ in range(200):
        p_correct_from_max = update_mastery(p_correct_from_max, True, "hard")
        assert bkt_config.MIN_P <= p_correct_from_max <= bkt_config.MAX_P
    assert p_correct_from_max == pytest.approx(bkt_config.MAX_P)

    # Even if an un-clamped raw extreme is passed (0.0 or 1.0), output stays clamped
    assert bkt_config.MIN_P <= update_mastery(0.0, False, "medium") <= bkt_config.MAX_P
    assert bkt_config.MIN_P <= update_mastery(1.0, True, "medium") <= bkt_config.MAX_P


def test_recovery_from_min_p():
    """Verifies that from MIN_P, a sequence of correct answers recovers and crosses the 0.80 threshold."""
    p = bkt_config.MIN_P
    steps = 0
    max_steps = 20

    while p < 0.80 and steps < max_steps:
        p = update_mastery(p, True, "medium")
        steps += 1

    assert p >= 0.80, f"Failed to recover above 0.80 within {max_steps} steps (reached {p})"
    assert steps <= 10, f"Expected rapid recovery, took {steps} steps"


def test_order_matters_in_sequential_answers():
    """Verifies that apply_answers([correct, wrong]) produces a different result from [wrong, correct]."""
    p_start = 0.30
    seq_correct_wrong = [(True, "medium"), (False, "medium")]
    seq_wrong_correct = [(False, "medium"), (True, "medium")]

    res_cw = apply_answers(p_start, seq_correct_wrong)
    res_wc = apply_answers(p_start, seq_wrong_correct)

    assert res_cw != pytest.approx(res_wc), f"Order should matter: {res_cw} == {res_wc}"
    # Verify exact sequential values
    # Correct then wrong: 0.30 -> ~0.6461 -> ~0.2762
    # Wrong then correct: 0.30 -> ~0.1486 -> ~0.4474
    assert res_cw == pytest.approx(0.2762, abs=1e-3)
    assert res_wc == pytest.approx(0.4474, abs=1e-3)


def test_unknown_difficulty_and_difficulty_aware_fallback(monkeypatch):
    """Verifies unknown/None difficulties and DIFFICULTY_AWARE=False fallback to medium parameters."""
    p = 0.30
    expected_medium_correct = update_mastery(p, True, "medium")
    expected_medium_wrong = update_mastery(p, False, "medium")

    # None difficulty
    assert update_mastery(p, True, None) == expected_medium_correct
    assert update_mastery(p, False, None) == expected_medium_wrong

    # Unknown difficulty string
    assert update_mastery(p, True, "extreme") == expected_medium_correct
    assert update_mastery(p, True, "") == expected_medium_correct

    # Case-insensitive and whitespace handling
    assert update_mastery(p, True, "Medium") == expected_medium_correct
    assert update_mastery(p, True, "  EASY  ") == update_mastery(p, True, "easy")
    assert update_mastery(p, True, "HaRd") == update_mastery(p, True, "hard")

    # DIFFICULTY_AWARE = False forces medium parameters for all inputs
    monkeypatch.setattr(bkt_config, "DIFFICULTY_AWARE", False)
    assert update_mastery(p, True, "easy") == expected_medium_correct
    assert update_mastery(p, True, "hard") == expected_medium_correct
    assert update_mastery(p, False, "easy") == expected_medium_wrong
    assert update_mastery(p, False, "hard") == expected_medium_wrong


def test_classification_rules_and_boundaries():
    """Verifies all competency classification boundaries and criteria per Section 4."""
    # 1. 0 answers (or <= 0) is always not_attempted regardless of probability
    assert classify(0.30, 0) == "not_attempted"
    assert classify(0.10, 0) == "not_attempted"
    assert classify(0.50, 0) == "not_attempted"
    assert classify(0.85, 0) == "not_attempted"
    assert classify(0.99, -1) == "not_attempted"

    # 2. Boundary: 0.39 vs 0.40
    # p < 0.40 -> weak
    assert classify(0.39, 1) == "weak"
    assert classify(0.3999, 10) == "weak"
    assert classify(0.01, 5) == "weak"

    # p == 0.40 -> developing
    assert classify(0.40, 1) == "developing"
    assert classify(0.4001, 10) == "developing"
    assert classify(0.60, 2) == "developing"

    # 3. Boundary: 0.79 vs 0.80
    assert classify(0.79, 5) == "developing"
    assert classify(0.7999, 10) == "developing"

    # 4. p >= 0.80 with fewer than 3 answers is developing
    assert classify(0.80, 1) == "developing"
    assert classify(0.80, 2) == "developing"
    assert classify(0.85, 2) == "developing"
    assert classify(0.99, 1) == "developing"

    # 5. p >= 0.80 with 3 or more answers is strong
    assert classify(0.80, 3) == "strong"
    assert classify(0.85, 3) == "strong"
    assert classify(0.85, 10) == "strong"
    assert classify(0.99, 4) == "strong"
