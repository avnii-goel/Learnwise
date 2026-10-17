"""Bayesian Knowledge Tracing (BKT) calculation engine.

Implements standard Corbett & Anderson (1994) knowledge tracing algorithms
and competency state classifications. Pure functional module with no database
or web framework dependencies.

Reference: docs/KNOWLEDGE_MODEL.md Sections 2, 3, and 4.
"""

from typing import Iterable, Sequence

from app.config import bkt as bkt_config


def update_mastery(
    p: float,
    is_correct: bool,
    difficulty: str | None = None
) -> float:
    """Updates a topic's mastery probability given an answered question.

    Formulas:
        If correct (obs = 1):
            posterior = (p * (1 - s)) / (p * (1 - s) + (1 - p) * g)
        If incorrect (obs = 0):
            posterior = (p * s) / (p * s + (1 - p) * (1 - g))
        Learning transition:
            p_new = posterior + (1 - posterior) * P_TRANSIT
        Clamping:
            p_final = min(max(p_new, MIN_P), MAX_P)

    Args:
        p: Current mastery probability prior to this evidence.
        is_correct: Whether the learner answered the question correctly.
        difficulty: Question difficulty ('easy', 'medium', 'hard'). Case-insensitive.
                    Unknown or None values fallback to 'medium'.

    Returns:
        float: Clamped updated mastery probability.
    """
    # 1. Resolve difficulty parameters
    if not bkt_config.DIFFICULTY_AWARE or difficulty is None:
        diff_key = "medium"
    else:
        normalized = difficulty.strip().lower()
        diff_key = normalized if normalized in bkt_config.DIFFICULTY_PARAMS else "medium"

    params = bkt_config.DIFFICULTY_PARAMS[diff_key]
    s = params["slip"]
    g = params["guess"]

    # 2. Bayesian posterior calculation
    if is_correct:
        numerator = p * (1.0 - s)
        denominator = numerator + (1.0 - p) * g
    else:
        numerator = p * s
        denominator = numerator + (1.0 - p) * (1.0 - g)

    posterior = numerator / denominator if denominator > 0 else p

    # 3. Practice transition acquisition
    p_new = posterior + (1.0 - posterior) * bkt_config.P_TRANSIT

    # 4. Numerical safety clamping
    return max(bkt_config.MIN_P, min(bkt_config.MAX_P, p_new))


def apply_answers(
    p: float,
    answers: Sequence[tuple[bool, str | None]] | Iterable[tuple[bool, str | None]]
) -> float:
    """Applies a sequence of question answers in order, updating running mastery.

    Args:
        p: Starting mastery probability.
        answers: Sequence of (is_correct, difficulty) tuples in execution order.

    Returns:
        float: Final mastery probability after sequential updates.
    """
    current_p = p
    for is_correct, difficulty in answers:
        current_p = update_mastery(current_p, is_correct, difficulty)
    return current_p


def classify(p: float, total_answers: int) -> str:
    """Classifies topic competency status from mastery probability and answer count.

    Classification rules (evaluated dynamically on read, never stored):
        - not_attempted: total_answers == 0 (including unrecorded topics)
        - weak:          total_answers > 0 and p < 0.40
        - developing:    0.40 <= p < 0.80, or (p >= 0.80 and total_answers < 3)
        - strong:        p >= 0.80 and total_answers >= 3

    Args:
        p: Current mastery probability.
        total_answers: Total questions answered under this topic across all attempts.

    Returns:
        str: One of 'not_attempted', 'weak', 'developing', or 'strong'.
    """
    if total_answers <= 0:
        return bkt_config.STATUS_NOT_ATTEMPTED

    if p < bkt_config.THRESHOLD_WEAK:
        return bkt_config.STATUS_WEAK

    if p >= bkt_config.THRESHOLD_STRONG and total_answers >= bkt_config.MIN_ANSWERS_STRONG:
        return bkt_config.STATUS_STRONG

    return bkt_config.STATUS_DEVELOPING
