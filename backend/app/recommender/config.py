"""Configuration constants for LearnWise Recommender Engine.

Reference: docs/RECOMMENDER.md Sections 2, 3, 5, 6, 7, 8, and 9.
"""

from typing import Any

# Re-export Phase 5 BKT mastery status thresholds (do not redefine)
from app.config.bkt import (
    STATUS_NOT_ATTEMPTED,
    STATUS_WEAK,
    STATUS_DEVELOPING,
    STATUS_STRONG,
    THRESHOLD_WEAK,
    THRESHOLD_STRONG,
    MIN_ANSWERS_STRONG,
)

# 1. Embedding Model Configuration
MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
FALLBACK_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: int = 384
BATCH_SIZE: int = 32

# 2. Pipeline Boundaries
MAX_TARGET_TOPICS: int = 3
RESOURCES_PER_TOPIC: int = 3

# 3. Difficulty Target Thresholds (Section 6.1)
# - Easy: mastery < 0.40 (or not_attempted)
# - Medium: 0.40 <= mastery < 0.70
# - Hard: mastery >= 0.70
DIFFICULTY_TARGET_EASY_MAX: float = 0.40
DIFFICULTY_TARGET_MEDIUM_MAX: float = 0.70
DIFFICULTY_THRESHOLDS: tuple[float, float] = (0.40, 0.70)

# Difficulty scale mapping: easy=0, medium=1, hard=2
DIFFICULTY_RANKS: dict[str, int] = {
    "easy": 0,
    "medium": 1,
    "hard": 2,
}

# 4. Target Selection & Need Constants (Section 5)
NOT_ATTEMPTED_NEED: float = 0.50

# 5. Peer Neighborhood & Similarity Constants (Section 7)
K_NEIGHBORS: int = 10
MIN_SHARED_TOPICS: int = 3
MIN_SIMILARITY: float = 0.75

# 6. Collaborative Attribution Constants (Section 8)
IMPROVEMENT_MARGIN: float = 0.05

# 7. Online Query Construction (Section 3.3)
WRONG_ANSWERS_IN_QUERY: int = 3

# 8. Scoring Strategy Profiles & Component Weights (Section 9.2)
STRATEGIES: dict[str, dict[str, float]] = {
    "hybrid": {
        "need": 0.30,
        "semantic": 0.30,
        "difficulty": 0.15,
        "collab": 0.25,
    },
    "content_only": {
        "need": 0.40,
        "semantic": 0.40,
        "difficulty": 0.20,
        "collab": 0.0,
    },
}

