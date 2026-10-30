#!/usr/bin/env python3
"""Offline learning resource embedding script for LearnWise.

Generates dense vector embeddings for learning resources using the active embedder.
Only stale or missing rows (embedding IS NULL or embedding_hash mismatch) are embedded,
unless --all is specified.

Usage:
    python scripts/embed_resources.py [--dry-run] [--all]
"""

import argparse
import os
import sys
from typing import Any

# Ensure backend directory is in sys.path and load environment
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from sqlalchemy.orm import Session, joinedload
from app.database import SessionLocal
from app.models.learningresource import LearningResource
from app.models.topic import Topic
from app.recommender.config import BATCH_SIZE
from app.recommender.embedding import (
    Embedder,
    get_embedder,
    build_resource_text,
    embedding_hash,
)


def embed_resources(
    db: Session,
    dry_run: bool = False,
    force_all: bool = False,
    embedder: Embedder | None = None
) -> dict[str, Any]:
    """Generates and persists embeddings for stale or un-embedded resources.

    Args:
        db: SQLAlchemy database session.
        dry_run: If True, simulates embedding calculation without persisting to DB.
        force_all: If True, re-embeds every resource regardless of hash match.
        embedder: Optional custom embedder (defaults to get_embedder()).

    Returns:
        dict: Summary statistics including total, embedded, skipped counts.
    """
    active_embedder = embedder or get_embedder()

    resources = (
        db.query(LearningResource)
        .options(joinedload(LearningResource.topic))
        .order_by(LearningResource.id)
        .all()
    )

    to_embed: list[tuple[LearningResource, str, str]] = []
    skipped_count = 0

    for res in resources:
        topic_title = res.topic.title if res.topic else ""
        text = build_resource_text(topic_title, res.title, res.description or "")
        current_hash = embedding_hash(active_embedder.model_name, text)

        needs_embed = (
            force_all
            or res.embedding is None
            or res.embedding_hash != current_hash
        )

        if needs_embed:
            to_embed.append((res, text, current_hash))
        else:
            skipped_count += 1

    embedded_count = 0

    # Process in batches of 32
    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i : i + BATCH_SIZE]
        batch_texts = [item[1] for item in batch]
        batch_vectors = active_embedder.embed(batch_texts)

        for (res, _, target_hash), vector in zip(batch, batch_vectors):
            res.embedding = vector
            res.embedding_hash = target_hash

        embedded_count += len(batch)

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "total": len(resources),
        "embedded": embedded_count,
        "skipped": skipped_count,
        "dry_run": dry_run,
        "model_name": active_embedder.model_name,
    }


def main():
    parser = argparse.ArgumentParser(description="LearnWise Learning Resource Embedder")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate embedding process without committing to database"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Force re-embedding of all resources regardless of existing hash"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        active_embedder = get_embedder()
        mode_str = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{mode_str}=== LearnWise Learning Resource Embedding ===")
        print(f"Model       : {active_embedder.model_name}")
        print(f"Force All   : {args.all}")
        print(f"Mode        : {'Dry Run (Simulated)' if args.dry_run else 'Live Commit'}")

        result = embed_resources(
            db=db,
            dry_run=args.dry_run,
            force_all=args.all,
            embedder=active_embedder
        )

        print(f"Total       : {result['total']}")
        print(f"Embedded    : {result['embedded']}")
        print(f"Skipped     : {result['skipped']}")
        print("================================================\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()

