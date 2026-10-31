"""Adaptive quizzing question selection and difficulty progression engine.

Reference: docs/ADAPTIVE_QUIZ.md Sections 2, 3, 4, 5.
Pure algorithmic engine with zero database dependencies.
"""

from datetime import datetime, timezone
import random
from typing import Any, NamedTuple, Sequence

from app.recommender.config import (
    DIFFICULTY_TARGET_EASY_MAX,
    DIFFICULTY_TARGET_MEDIUM_MAX,
)
from app.recommender.scoring import difficulty_rank
from app.services.bkt import update_mastery

# 1. Pipeline Constants
ADAPTIVE_QUIZ_LENGTH: int = 8

# 2. Selection Reasons
SELECTION_UNSEEN_AT_TARGET: str = "unseen_at_target"
SELECTION_UNSEEN_OTHER_LEVEL: str = "unseen_other_level"
SELECTION_SEEN_REUSED: str = "seen_reused"
ALLOWED_SELECTION_REASONS: set[str] = {
    SELECTION_UNSEEN_AT_TARGET,
    SELECTION_UNSEEN_OTHER_LEVEL,
    SELECTION_SEEN_REUSED,
}


class SelectionResult(NamedTuple):
    """Result of adaptive question selection containing the question and selection audit reason."""
    question: Any
    selection_reason: str


def target_difficulty(p: float | None) -> str:
    """Computes target difficulty string ('easy', 'medium', 'hard') based on running mastery p.

    Cutoffs:
    - easy: p < 0.40 (or None / unattempted)
    - medium: 0.40 <= p < 0.70
    - hard: p >= 0.70
    """
    if p is None or p < DIFFICULTY_TARGET_EASY_MAX:
        return "easy"
    if p < DIFFICULTY_TARGET_MEDIUM_MAX:
        return "medium"
    return "hard"


def target_difficulty_rank(p: float | None) -> int:
    """Computes target difficulty rank (0, 1, 2) based on running mastery p."""
    return difficulty_rank(target_difficulty(p))


def advance_running_mastery(
    p_running: float,
    is_correct: bool,
    difficulty: str | None,
) -> float:
    """Advances the running topic mastery estimate using the canonical BKT update.

    Delegates strictly to app.services.bkt.update_mastery without reimplementing equations.
    """
    return update_mastery(p_running, is_correct, difficulty)


def _get_candidate_id(c: Any) -> int:
    """Extracts identifier from a candidate object or dictionary."""
    if isinstance(c, dict):
        val = c.get("id") if "id" in c else c.get("question_id")
        if val is not None:
            return int(val)
        raise ValueError(f"Candidate dict missing 'id' or 'question_id': {c}")
    val = getattr(c, "id", None) or getattr(c, "question_id", None)
    if val is not None:
        return int(val)
    raise ValueError(f"Candidate object missing 'id' or 'question_id': {c}")


def _get_candidate_difficulty(c: Any) -> str:
    """Extracts difficulty string from a candidate object or dictionary."""
    if isinstance(c, dict):
        return str(c.get("difficulty", "medium"))
    return str(getattr(c, "difficulty", "medium"))


def _seen_timestamp_key(cid: int, last_seen_dict: dict[int, Any] | None) -> datetime:
    """Normalizes historical answered_at timestamp for comparison (least recently answered first)."""
    if not last_seen_dict or cid not in last_seen_dict:
        # If seen but timestamp missing, treat as oldest possible
        return datetime.min.replace(tzinfo=timezone.utc)
    ts = last_seen_dict[cid]
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    return ts


def choose_next_question(
    candidates: Sequence[Any],
    target: str | int,
    seen_ids: set[int] | Sequence[int] | None = None,
    last_seen_at: dict[int, Any] | None = None,
    rng: random.Random | None = None,
) -> SelectionResult:
    """Selects the optimal question for the next step of an adaptive quiz session.

    Algorithm (docs/ADAPTIVE_QUIZ.md Section 5):
    1. For each candidate question:
       cost = |rank(q) - target_rank| + seen_penalty(q)
       where seen_penalty = 1 if q has been answered previously by learner, else 0.
    2. Sort candidates by cost ascending.
    3. Break ties in strict hierarchical order:
       - Unseen first (seen_penalty == 0 beats seen_penalty == 1)
       - Easier level first (rank(q) ascending)
       - Least recently answered (oldest historical answered_at timestamp)
       - Deterministic RNG selection among remaining exact ties.
    4. Tag selection with appropriate reason:
       - 'unseen_at_target': rank == target_rank and not seen
       - 'unseen_other_level': rank != target_rank and not seen
       - 'seen_reused': seen in prior attempts (reused)

    Args:
        candidates: Sequence of question items (dictionaries or objects).
        target: Target difficulty level (string 'easy'/'medium'/'hard' or integer rank 0/1/2).
        seen_ids: Set of question IDs answered by this learner in prior attempts.
        last_seen_at: Optional mapping of question_id -> answered_at timestamp for seen questions.
        rng: Optional random.Random instance for deterministic reproducibility.

    Returns:
        SelectionResult: (chosen_question, selection_reason).

    Raises:
        ValueError: If candidates sequence is empty.
    """
    if not candidates:
        raise ValueError("Candidate question pool cannot be empty.")

    target_rank = target if isinstance(target, int) else difficulty_rank(target)
    seen_set = set(seen_ids) if seen_ids else set()
    rand = rng if rng is not None else random

    scored_candidates = []
    for c in candidates:
        cid = _get_candidate_id(c)
        diff_str = _get_candidate_difficulty(c)
        rank = difficulty_rank(diff_str)
        is_seen = 1 if cid in seen_set else 0
        cost = abs(rank - target_rank) + is_seen
        ts_key = _seen_timestamp_key(cid, last_seen_at) if is_seen else datetime.min.replace(tzinfo=timezone.utc)

        sort_key = (cost, is_seen, rank, ts_key)
        scored_candidates.append((sort_key, c, cid, rank, is_seen))

    # Find the minimum sort key across all candidates
    min_sort_key = min(item[0] for item in scored_candidates)

    # Collect all candidates sharing the exact minimum key
    tied_candidates = [
        (c, cid, rank, is_seen)
        for sort_key, c, cid, rank, is_seen in scored_candidates
        if sort_key == min_sort_key
    ]

    # Deterministic tie-break if multiple candidates remain identical across all 4 criteria
    if len(tied_candidates) == 1:
        chosen, chosen_id, chosen_rank, chosen_is_seen = tied_candidates[0]
    else:
        chosen, chosen_id, chosen_rank, chosen_is_seen = rand.choice(tied_candidates)

    # Determine selection reason
    if chosen_is_seen == 0:
        if chosen_rank == target_rank:
            reason = SELECTION_UNSEEN_AT_TARGET
        else:
            reason = SELECTION_UNSEEN_OTHER_LEVEL
    else:
        reason = SELECTION_SEEN_REUSED

    return SelectionResult(question=chosen, selection_reason=reason)

