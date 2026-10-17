"""Bayesian Knowledge Tracing (BKT) configuration constants and classification thresholds.

Reference: docs/KNOWLEDGE_MODEL.md Sections 2, 3, and 4.
Corbett, A. T., & Anderson, J. R. (1994). Knowledge tracing: Modeling the acquisition of procedural knowledge.
"""

# Global BKT Model Parameters
# Note: These values are heuristic baselines commonly used in EDM literature, not fitted from data.
P_INIT: float = 0.30
"""Prior mastery probability before any interaction evidence is recorded."""

P_TRANSIT: float = 0.10
"""Probability of transitioning from unmastered to mastered state after a practice opportunity."""

MIN_P: float = 0.01
"""Lower safety bound to prevent probability saturation (zero-collapse)."""

MAX_P: float = 0.99
"""Upper safety bound to prevent probability saturation (ceiling-lock)."""

DIFFICULTY_AWARE: bool = True
"""Flag determining whether question difficulty adjusts slip and guess parameters.
When False, the engine strictly defaults to the 'medium' parameter row."""

# Slip and Guess parameters per question difficulty level
DIFFICULTY_PARAMS: dict[str, dict[str, float]] = {
    "easy": {
        "slip": 0.05,
        "guess": 0.30,
    },
    "medium": {
        "slip": 0.10,
        "guess": 0.25,
    },
    "hard": {
        "slip": 0.15,
        "guess": 0.20,
    },
}

# Competency Classification Categories
STATUS_NOT_ATTEMPTED: str = "not_attempted"
STATUS_WEAK: str = "weak"
STATUS_DEVELOPING: str = "developing"
STATUS_STRONG: str = "strong"

# Classification Thresholds (evaluated on read, never stored)
# - not_attempted: total_answers == 0
# - weak: p < THRESHOLD_WEAK (0.40)
# - developing: THRESHOLD_WEAK <= p < THRESHOLD_STRONG (0.80), or p >= THRESHOLD_STRONG with < MIN_ANSWERS_STRONG
# - strong: p >= THRESHOLD_STRONG and total_answers >= MIN_ANSWERS_STRONG (3)
THRESHOLD_WEAK: float = 0.40
THRESHOLD_STRONG: float = 0.80
MIN_ANSWERS_STRONG: int = 3
