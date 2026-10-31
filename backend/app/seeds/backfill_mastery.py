"""Historical quiz attempt replay and mastery backfill script.

Replays past quiz attempts into topic_mastery and topic_mastery_history using
the live Bayesian Knowledge Tracing (BKT) engine (app.services.mastery.apply_attempt).

Per-User Idempotency Rules:
- If a user has NO topic_mastery or topic_mastery_history rows, all of that user's
  attempts are replayed in chronological order (attempt.id ASC, response.id ASC).
- If a user already has mastery or history records, that user is SKIPPED and a warning
  is logged naming the user ID and unprocessed attempts count.
- Rebuilding a user's mastery is supported strictly via --rebuild-user <user_id>,
  which atomically deletes that user's mastery/history and replays all attempts in order.
- --rebuild-all is explicitly forbidden.
- --dry-run simulates the execution inside a transaction and rolls back at the end.
"""

import argparse
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.services.mastery import apply_attempt


def run_backfill(
    db: Session,
    dry_run: bool = False,
    rebuild_user_id: int | None = None
) -> dict:
    """Replays historical quiz attempts for users without mastery or for a specific user.

    Args:
        db: SQLAlchemy database session.
        dry_run: If True, simulates changes and rolls back the transaction.
        rebuild_user_id: Explicit user ID to wipe and rebuild. If None, backfills
                         users who have zero existing mastery/history rows.

    Returns:
        dict: Summary statistics of the backfill execution.
    """
    mode_str = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode_str}=== LearnWise Mastery Historical Backfill ===")

    stats = {
        "users_inspected": 0,
        "users_backfilled": 0,
        "users_skipped": 0,
        "attempts_replayed": 0,
        "mastery_rows_created": 0,
        "history_rows_created": 0,
        "deleted_mastery_rows": 0,
        "deleted_history_rows": 0,
        "dry_run": dry_run,
        "rebuild_user_id": rebuild_user_id,
    }

    try:
        # Determine candidate users
        if rebuild_user_id is not None:
            user = db.query(User).filter(User.id == rebuild_user_id).first()
            if not user:
                print(f"ERROR: User with id {rebuild_user_id} does not exist.")
                return stats
            target_user_ids = [rebuild_user_id]
        else:
            # All users with at least one completed quiz attempt
            target_user_ids = [
                row[0]
                for row in (
                    db.query(QuizAttempt.user_id)
                    .filter(QuizAttempt.status == "completed")
                    .distinct()
                    .order_by(QuizAttempt.user_id.asc())
                    .all()
                )
            ]

        stats["users_inspected"] = len(target_user_ids)
        print(f"{mode_str}Found {len(target_user_ids)} candidate user(s) with quiz attempts.")

        for user_id in target_user_ids:
            # Check existing mastery/history
            existing_mastery_count = (
                db.query(TopicMastery).filter(TopicMastery.user_id == user_id).count()
            )
            existing_history_count = (
                db.query(TopicMasteryHistory)
                .filter(TopicMasteryHistory.user_id == user_id)
                .count()
            )
            has_existing = (existing_mastery_count > 0) or (existing_history_count > 0)

            # Rebuild mode: explicit wipe and rebuild
            if rebuild_user_id is not None and user_id == rebuild_user_id:
                print(
                    f"{mode_str}--rebuild-user {user_id}: Deleting {existing_mastery_count} topic_mastery "
                    f"and {existing_history_count} topic_mastery_history rows..."
                )
                stats["deleted_mastery_rows"] += existing_mastery_count
                stats["deleted_history_rows"] += existing_history_count

                db.query(TopicMasteryHistory).filter(TopicMasteryHistory.user_id == user_id).delete()
                db.query(TopicMastery).filter(TopicMastery.user_id == user_id).delete()
                db.flush()

            # Normal backfill mode: skip if already has history/mastery
            elif has_existing:
                user_attempts_count = (
                    db.query(QuizAttempt)
                    .filter(QuizAttempt.user_id == user_id, QuizAttempt.status == "completed")
                    .count()
                )
                print(
                    f"WARNING: Skipping user {user_id}: user already has mastery/history records "
                    f"({user_attempts_count} attempts left unprocessed). Use --rebuild-user {user_id} to replay."
                )
                stats["users_skipped"] += 1
                continue

            # Load all completed attempts for this user in chronological order
            user_attempts = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == user_id, QuizAttempt.status == "completed")
                .order_by(QuizAttempt.id.asc())
                .all()
            )

            if not user_attempts:
                print(f"{mode_str}User {user_id} has 0 quiz attempts.")
                continue

            print(
                f"{mode_str}Replaying {len(user_attempts)} attempt(s) for user {user_id}..."
            )

            user_history_before = (
                db.query(TopicMasteryHistory).filter(TopicMasteryHistory.user_id == user_id).count()
            )
            user_mastery_before = (
                db.query(TopicMastery).filter(TopicMastery.user_id == user_id).count()
            )

            for attempt in user_attempts:
                # Load responses strictly in response ID order
                responses = (
                    db.query(QuizResponse)
                    .filter(QuizResponse.attempt_id == attempt.id)
                    .order_by(QuizResponse.id.asc())
                    .all()
                )
                as_of = attempt.completed_at or attempt.started_at
                apply_attempt(db, user_id, attempt, responses, as_of=as_of)

            db.flush()

            user_history_after = (
                db.query(TopicMasteryHistory).filter(TopicMasteryHistory.user_id == user_id).count()
            )
            user_mastery_after = (
                db.query(TopicMastery).filter(TopicMastery.user_id == user_id).count()
            )

            stats["users_backfilled"] += 1
            stats["attempts_replayed"] += len(user_attempts)
            stats["mastery_rows_created"] += (user_mastery_after - user_mastery_before)
            stats["history_rows_created"] += (user_history_after - user_history_before)

        if dry_run:
            db.rollback()
            print(f"\n[DRY RUN] Transaction rolled back. ZERO changes were written to the database.")
        else:
            db.commit()
            print(f"\n[COMMITTED] Transaction committed successfully.")

        # Print final summary
        print("=== Backfill Summary ===")
        print(f"Users Inspected      : {stats['users_inspected']}")
        print(f"Users Backfilled     : {stats['users_backfilled']}")
        print(f"Users Skipped        : {stats['users_skipped']}")
        print(f"Attempts Replayed    : {stats['attempts_replayed']}")
        print(f"Mastery Rows Created : {stats['mastery_rows_created']}")
        print(f"History Rows Created : {stats['history_rows_created']}")
        if stats["deleted_mastery_rows"] or stats["deleted_history_rows"]:
            print(f"Mastery Rows Deleted : {stats['deleted_mastery_rows']}")
            print(f"History Rows Deleted : {stats['deleted_history_rows']}")
        print(f"Dry Run              : {stats['dry_run']}")
        print("========================\n")

        return stats

    except Exception as e:
        db.rollback()
        print(f"ERROR: Exception occurred during backfill: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="LearnWise BKT Mastery Historical Backfill Script")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate backfill without persisting changes (rolls back transaction at completion)"
    )
    parser.add_argument(
        "--rebuild-user",
        type=int,
        default=None,
        metavar="USER_ID",
        help="Atomic delete and replay for a specific user ID"
    )
    parser.add_argument(
        "--rebuild-all",
        action="store_true",
        help=argparse.SUPPRESS
    )

    args = parser.parse_args()

    if args.rebuild_all:
        sys.exit(
            "ERROR: --rebuild-all is prohibited. Rebuilding mastery requires an explicit "
            "--rebuild-user <user_id> to prevent accidental bulk loss of mastery state."
        )

    db = SessionLocal()
    try:
        run_backfill(db, dry_run=args.dry_run, rebuild_user_id=args.rebuild_user)
    finally:
        db.close()


if __name__ == "__main__":
    main()
