#!/usr/bin/env python3
"""Simulate recommendation clicks for synthetic learners.

NOTICE: This script generates simulated feedback that only proves the pipeline works;
it is NOT evidence of learning gains.

Generates impressions and simulates engagement clicks across synthetic learners
for collaborative filtering validation and testing.

Usage:
    python scripts/simulate_recommendation_clicks.py [--dry-run] [--rebuild]
"""

import argparse
from datetime import datetime, timezone
import hashlib
import os
import random
import sys
from typing import Any
import uuid

# Ensure backend directory is in sys.path and load environment
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.recommendation_impression import RecommendationImpression
from app.models.user import User
from app.recommender.embedding import Embedder, get_embedder
from app.recommender.service import recommend_for_user
from app.seeds.seed_synthetic_learners import (
    DEFAULT_NUM_LEARNERS,
    SYNTHETIC_EMAIL_PATTERN,
)

EXPECTED_SYNTHETIC_LEARNERS = DEFAULT_NUM_LEARNERS


def compute_resource_quality(resource_id: int) -> float:
    """Computes a deterministic quality value in [0.2, 0.9] from SHA-256 hash of resource_id."""
    h = hashlib.sha256(f"resource_quality:{resource_id}".encode("utf-8")).hexdigest()
    ratio = (int(h[:8], 16) % 100000) / 100000.0
    return 0.2 + 0.7 * ratio


def simulate_recommendation_clicks(
    db: Session,
    dry_run: bool = False,
    rebuild: bool = False,
    seed: int = 42,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Simulates recommendation requests and engagement clicks for synthetic learners.

    Args:
        db: SQLAlchemy database session.
        dry_run: If True, calculates impressions/clicks without persisting.
        rebuild: If True, deletes existing is_synthetic=true impression rows first.
        seed: Random seed for deterministic simulation.
        embedder: Optional custom embedder (defaults to get_embedder()).

    Returns:
        dict: Summary counts of impressions, clicks, helped items, and deleted rows.
    """
    # 1. Verification guard: Verify all expected synthetic learners exist
    expected_count = EXPECTED_SYNTHETIC_LEARNERS
    synthetic_users = (
        db.query(User)
        .filter(User.email.like(SYNTHETIC_EMAIL_PATTERN))
        .order_by(User.id.asc())
        .all()
    )
    actual_count = len(synthetic_users)
    if actual_count != expected_count:
        error_msg = (
            f"Synthetic learner validation failed: expected {expected_count} synthetic learners "
            f"matching '{SYNTHETIC_EMAIL_PATTERN}', but found {actual_count} in database. "
            f"Please run python -m app.seeds.seed_synthetic_learners first."
        )
        print(f"ERROR: {error_msg}", file=sys.stderr)
        raise RuntimeError(error_msg)

    # 2. Rebuild step: delete ONLY is_synthetic=True rows
    deleted_count = 0
    if rebuild:
        existing_synthetic_query = db.query(RecommendationImpression).filter(
            RecommendationImpression.is_synthetic.is_(True)
        )
        deleted_count = existing_synthetic_query.count()
        if dry_run:
            print(f"[DRY RUN] Would delete {deleted_count} existing synthetic impression rows.")
        else:
            existing_synthetic_query.delete(synchronize_session=False)
            db.commit()
            print(f"Deleted {deleted_count} existing synthetic impression rows.")

    # 3. Simulate recommendations and clicks
    rng = random.Random(seed)
    active_embedder = embedder or get_embedder()

    total_impressions = 0
    total_clicks = 0
    total_helped = 0
    impressions_to_write: list[RecommendationImpression] = []

    now = datetime.now(timezone.utc)

    for user in synthetic_users:
        # Call recommend_for_user with content_only strategy in-process
        result = recommend_for_user(
            db,
            user_id=user.id,
            strategy="content_only",
            embedder=active_embedder,
        )

        request_id = uuid.uuid4()

        for item in result.items:
            total_impressions += 1
            # Click probability = 0.4
            is_clicked = rng.random() < 0.4
            # Quality in [0.2, 0.9]
            quality = compute_resource_quality(item.resource_id)
            is_helped = is_clicked and (rng.random() < quality)

            if is_clicked:
                total_clicks += 1
            if is_helped:
                total_helped += 1

            # Determine mastery_at_shown:
            # - For non-helped items: current mastery
            # - For helped items: current mastery minus 0.10 (clamped to 0.0)
            # - For unattempted topics (mastery is None): None
            if item.mastery is not None:
                if is_helped:
                    mastery_val = max(0.0, item.mastery - 0.10)
                else:
                    mastery_val = item.mastery
            else:
                mastery_val = None

            imp = RecommendationImpression(
                user_id=user.id,
                resource_id=item.resource_id,
                topic_id=item.topic_id,
                request_id=request_id,
                strategy="content_only",
                rank=item.rank,
                score=item.score,
                mastery_at_shown=mastery_val,
                components=item.components,
                reason=item.reason,
                shown_at=now,
                clicked_at=now if is_clicked else None,
                is_synthetic=True,
            )
            impressions_to_write.append(imp)

    if not dry_run and impressions_to_write:
        db.add_all(impressions_to_write)
        db.commit()

    mode_prefix = "[DRY RUN] " if dry_run else ""
    print(
        f"{mode_prefix}Simulation complete: {total_impressions} impressions, "
        f"{total_clicks} clicks ({total_helped} helped) across {len(synthetic_users)} learners."
    )

    return {
        "impressions": total_impressions,
        "clicks": total_clicks,
        "helped": total_helped,
        "deleted": deleted_count,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Simulate recommendation impressions and clicks for synthetic learners."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without committing changes to database.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing synthetic impressions before simulating.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic simulation (default: 42).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        simulate_recommendation_clicks(
            db=db,
            dry_run=args.dry_run,
            rebuild=args.rebuild,
            seed=args.seed,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

