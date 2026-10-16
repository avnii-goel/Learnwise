"""Seed demo accounts for LearnWise.

Creates one learner and one instructor demo account only when SEED_DEMO_USERS=true.
"""

import os
import sys

# Ensure backend root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.user import User
from app.utils.security import hash_password

DEMO_USERS = [
    {
        "name": "Demo Learner",
        "email": "learner@learnwise.com",
        "role": "learner",
    },
    {
        "name": "Demo Instructor",
        "email": "instructor@learnwise.com",
        "role": "instructor",
    },
]


def seed_demo_users(db: Session) -> tuple[int, int]:
    """Get-or-create demo learner and instructor accounts when SEED_DEMO_USERS=true.

    Returns (created_count, skipped_count).
    """
    seed_enabled = os.getenv("SEED_DEMO_USERS", "").strip().lower() in ("true", "1", "yes")
    if not seed_enabled:
        print("SEED_DEMO_USERS is not enabled ('true'). Skipping demo users seeding.")
        return 0, 0

    password = os.getenv("SEED_DEMO_PASSWORD")
    if not password:
        raise RuntimeError(
            "SEED_DEMO_USERS is set to true, but SEED_DEMO_PASSWORD is not set in the environment or .env."
        )

    hashed_pw = hash_password(password)
    created = 0
    skipped = 0

    for user_info in DEMO_USERS:
        existing = (
            db.query(User)
            .filter(User.email == user_info["email"])
            .first()
        )
        if existing:
            skipped += 1
        else:
            new_user = User(
                name=user_info["name"],
                email=user_info["email"],
                password_hash=hashed_pw,
                role=user_info["role"],
            )
            db.add(new_user)
            created += 1

    db.commit()
    return created, skipped


def run():
    """Standalone runner for seed_users."""
    db = SessionLocal()
    try:
        created, skipped = seed_demo_users(db)
        print(f"Demo Users: {created} created, {skipped} skipped")
    except Exception as e:
        db.rollback()
        print(f"Error seeding demo users: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
