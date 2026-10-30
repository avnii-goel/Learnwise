"""Synthetic learner population seed script.

Generates 50 synthetic learners across 5 structured archetypes (Groups A-E)
with simulated quiz attempts and responses evaluated through a 3PL logistic IRT model
and traced via the live Bayesian Knowledge Tracing (BKT) engine.

Supports:
- Deterministic reproducibility using random.Random(42)
- Idempotent execution (skips existing synthetic emails)
- --dry-run simulation without committing
- --reset-synthetic (--yes required) to clean up only synthetic accounts
- Scalable learner counts (--learners N, default 50)
"""

import argparse
import math
import os
import random
import secrets
import string
import sys
from datetime import datetime, timezone, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.course import Course
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.topic_mastery_history import TopicMasteryHistory
from app.models.user import User
from app.services.bkt import classify
from app.services.mastery import apply_attempt
from app.services.quiz import select_quiz_questions
from app.utils.security import hash_password

DEFAULT_NUM_LEARNERS = 50
SYNTHETIC_EMAIL_DOMAIN = "@synthetic.learnwise.test"
SYNTHETIC_EMAIL_PATTERN = "%@synthetic.learnwise.test"

REQUIRED_COURSE_TITLES = [
    "Computer Networks",
    "OOPS",
    "SQL/DBMS",
    "Operating Systems",
]

ARCHETYPES = {
    "A": {
        "name": "Group A (Strong Everywhere)",
        "centers": {
            "Computer Networks": 0.80,
            "Operating Systems": 0.80,
            "OOPS": 0.80,
            "SQL/DBMS": 0.80,
        },
        "topic_noise_std": 0.08,
    },
    "B": {
        "name": "Group B (Weak Everywhere)",
        "centers": {
            "Computer Networks": 0.30,
            "Operating Systems": 0.30,
            "OOPS": 0.30,
            "SQL/DBMS": 0.30,
        },
        "topic_noise_std": 0.08,
    },
    "C": {
        "name": "Group C (Strong Networks/OS, Weaker OOPS/SQL)",
        "centers": {
            "Computer Networks": 0.80,
            "Operating Systems": 0.80,
            "OOPS": 0.35,
            "SQL/DBMS": 0.35,
        },
        "topic_noise_std": 0.08,
    },
    "D": {
        "name": "Group D (Strong OOPS/SQL, Weaker Networks/OS)",
        "centers": {
            "Computer Networks": 0.35,
            "Operating Systems": 0.35,
            "OOPS": 0.80,
            "SQL/DBMS": 0.80,
        },
        "topic_noise_std": 0.08,
    },
    "E": {
        "name": "Group E (Average with Higher Topic Noise)",
        "centers": {
            "Computer Networks": 0.55,
            "Operating Systems": 0.55,
            "OOPS": 0.55,
            "SQL/DBMS": 0.55,
        },
        "topic_noise_std": 0.18,
    },
}

GROUP_KEYS = ["A", "B", "C", "D", "E"]

DIFFICULTY_OFFSETS = {
    "easy": 0.25,
    "medium": 0.50,
    "hard": 0.75,
}


def sigmoid(z: float) -> float:
    """Logistic sigmoid function with numerical guardrails."""
    if z < -40.0:
        return 0.0
    if z > 40.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def compute_p_correct(skill: float, difficulty: str | None = None) -> float:
    """Evaluates probability of answering correctly via 3PL logistic IRT model.

    Formula:
        P(correct) = 0.25 + 0.75 * sigmoid(5.0 * (skill - b))
    Offsets:
        easy: b = 0.25
        medium: b = 0.50
        hard: b = 0.75
    """
    b = DIFFICULTY_OFFSETS.get(str(difficulty).lower(), 0.50)
    return 0.25 + 0.75 * sigmoid(5.0 * (skill - b))


def get_or_generate_password() -> str:
    """Retrieves SYNTHETIC_PASSWORD from environment or generates a random throwaway password."""
    env_password = os.getenv("SYNTHETIC_PASSWORD")
    if env_password:
        return env_password

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    generated = "".join(secrets.choice(alphabet) for _ in range(16))
    print(f"[AUTH] Generated throwaway SYNTHETIC_PASSWORD: {generated}")
    return generated


def reset_synthetic_learners(db: Session, dry_run: bool = False, confirm_yes: bool = False) -> dict:
    """Removes all synthetic learners ending with @synthetic.learnwise.test."""
    synthetic_users = (
        db.query(User)
        .filter(User.email.like("%@synthetic.learnwise.test"))
        .all()
    )
    count = len(synthetic_users)
    print(f"\nFound {count} synthetic user(s) matching '@synthetic.learnwise.test'.")

    if not confirm_yes:
        print("ERROR: --reset-synthetic requires --yes confirmation to proceed. Aborting.")
        return {"deleted_users": 0, "status": "aborted_no_confirm"}

    if dry_run:
        print(f"[DRY RUN] Would delete {count} synthetic user(s) and their cascading data.")
        return {"deleted_users": count, "status": "dry_run"}

    for user in synthetic_users:
        db.delete(user)
    db.commit()

    print(f"Successfully deleted {count} synthetic user(s) and all cascading records.")
    return {"deleted_users": count, "status": "deleted"}


def seed_synthetic_learners(
    db: Session,
    num_learners: int = 50,
    learners_per_group: int | None = None,
    dry_run: bool = False,
    reset_synthetic: bool = False,
    confirm_yes: bool = False,
    base_time: datetime | None = None,
    seed: int = 42,
) -> dict:
    """Generates synthetic learner population, attempts, and BKT mastery state.

    Args:
        db: SQLAlchemy database session.
        num_learners: Total number of synthetic learners to generate (default 50).
        learners_per_group: If set, overrides num_learners to len(GROUP_KEYS) * learners_per_group.
        dry_run: If True, executes all work inside transactions and rolls back.
        reset_synthetic: If True, wipes existing synthetic users instead of seeding.
        confirm_yes: Required confirmation flag for --reset-synthetic.
        base_time: Anchor datetime for generating historical attempts (defaults to 2026-10-28 12:00 UTC).
        seed: Random seed for deterministic reproducibility (default 42).

    Returns:
        dict: Detailed execution statistics and competency distribution.
    """
    if reset_synthetic:
        return reset_synthetic_learners(db, dry_run=dry_run, confirm_yes=confirm_yes)

    if learners_per_group is not None and learners_per_group > 0:
        num_learners = len(GROUP_KEYS) * learners_per_group

    mode_str = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode_str}=== LearnWise Synthetic Learners Seed ({num_learners} learners) ===")

    # 1. Look up courses by EXACT title (never hard-code IDs)
    courses_by_title: dict[str, Course] = {}
    for title in REQUIRED_COURSE_TITLES:
        course = db.query(Course).filter(Course.title == title).first()
        if not course:
            raise RuntimeError(
                f"Missing required course '{title}' in database. "
                f"Please run seed_all.py first."
            )
        courses_by_title[title] = course

    resolved_mapping = {title: course.id for title, course in courses_by_title.items()}
    print(f"[COURSES] Resolved course titles to IDs: {resolved_mapping}")

    # Pre-cache topics and question pools per course
    topics_by_course_id: dict[int, list[Topic]] = {}
    questions_by_course_id: dict[int, list[Question]] = {}
    for title, course in courses_by_title.items():
        topics = (
            db.query(Topic)
            .filter(Topic.course_id == course.id)
            .order_by(Topic.order.asc(), Topic.id.asc())
            .all()
        )
        if not topics:
            raise RuntimeError(f"No topics found for course '{title}' (ID {course.id}).")
        topics_by_course_id[course.id] = topics
        topic_ids = [t.id for t in topics]

        questions = (
            db.query(Question)
            .filter(Question.topic_id.in_(topic_ids))
            .all()
        )
        if len(questions) < 20:
            raise RuntimeError(
                f"Course '{title}' has only {len(questions)} questions (minimum 20 required)."
            )
        questions_by_course_id[course.id] = questions

    # 2. Setup deterministic RNG and anchor time
    rng = random.Random(seed)
    if base_time is None:
        base_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    window_start = base_time - timedelta(days=30)

    # 3. Setup password hashing
    raw_password = get_or_generate_password()
    hashed_pw = hash_password(raw_password)

    stats = {
        "learners_requested": num_learners,
        "learners_created": 0,
        "learners_skipped": 0,
        "attempts_created": 0,
        "responses_created": 0,
        "mastery_rows_created": 0,
        "history_rows_created": 0,
        "dry_run": dry_run,
        "group_stats": {
            g: {
                "learners": 0,
                "attempts": 0,
                "total_responses": 0,
                "correct_responses": 0,
                "mastery_sum": 0.0,
                "mastery_count": 0,
                "statuses": {"not_attempted": 0, "weak": 0, "developing": 0, "strong": 0},
                "course_mastery": {t: [] for t in REQUIRED_COURSE_TITLES},
            }
            for g in GROUP_KEYS
        },
        "overall_statuses": {"not_attempted": 0, "weak": 0, "developing": 0, "strong": 0},
    }

    # 4. Generate each synthetic learner
    for idx in range(1, num_learners + 1):
        email = f"synthetic-{idx:02d}@synthetic.learnwise.test"
        name = f"Synthetic Learner {idx:02d}"

        # Idempotency check: skip if learner email already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"Skipping learner {email}: already exists in database.")
            stats["learners_skipped"] += 1
            continue

        # Map learner index to archetype group (A, B, C, D, E)
        if learners_per_group is not None and learners_per_group > 0:
            group_idx = min(4, (idx - 1) // learners_per_group)
        else:
            group_idx = min(4, (idx - 1) * 5 // num_learners)
        group_key = GROUP_KEYS[group_idx]
        archetype = ARCHETYPES[group_key]

        # Sample learner-specific course ability noise
        learner_noise = rng.gauss(0.0, 0.03)

        # Initialize topic skills per topic
        topic_skills: dict[int, float] = {}
        course_topic_ids_map: dict[int, list[int]] = {}

        for title, course in courses_by_title.items():
            course_center = archetype["centers"][title]
            course_ability = course_center + learner_noise
            c_topics = topics_by_course_id[course.id]
            course_topic_ids_map[course.id] = [t.id for t in c_topics]

            for topic in c_topics:
                t_noise = rng.gauss(0.0, archetype["topic_noise_std"])
                clamped_skill = max(0.05, min(0.95, course_ability + t_noise))
                topic_skills[topic.id] = clamped_skill

        # Plan attempts: Group E attempts only 2 of 4 courses; Groups A-D attempt all 4
        if group_key == "E":
            learner_course_titles = sorted(rng.sample(REQUIRED_COURSE_TITLES, 2))
        else:
            learner_course_titles = REQUIRED_COURSE_TITLES

        course_attempts_plan: list[tuple[Course, int]] = []
        for title in learner_course_titles:
            course = courses_by_title[title]
            n_attempts = rng.randint(2, 4)
            for attempt_seq in range(n_attempts):
                course_attempts_plan.append((course, attempt_seq))

        total_attempts = len(course_attempts_plan)

        # Generate strictly increasing timestamps across the 30-day window
        step_seconds = (28.0 * 86400.0) / max(1, total_attempts)
        scheduled_times: list[tuple[datetime, datetime]] = []
        for step_idx in range(total_attempts):
            t_sec = (step_idx + 1) * step_seconds + rng.uniform(-600.0, 600.0)
            completed_at = window_start + timedelta(seconds=t_sec)
            duration_sec = rng.randint(300, 1200)
            started_at = completed_at - timedelta(seconds=duration_sec)
            scheduled_times.append((started_at, completed_at))

        # Begin per-learner transaction
        try:
            user = User(
                name=name,
                email=email,
                password_hash=hashed_pw,
                role="learner",
            )
            db.add(user)
            db.flush()

            # Execute scheduled attempts chronologically
            for attempt_idx, (course, _) in enumerate(course_attempts_plan):
                started_at, completed_at = scheduled_times[attempt_idx]
                c_questions = questions_by_course_id[course.id]
                c_topic_ids = course_topic_ids_map[course.id]

                # Select 20 questions using canonical selection logic
                selected_q = select_quiz_questions(
                    c_questions,
                    c_topic_ids,
                    target_count=20,
                    rng=rng
                )

                attempt = QuizAttempt(
                    user_id=user.id,
                    course_id=course.id,
                    quiz_type="INITIAL",
                    score=0,
                    total_questions=len(selected_q),
                    started_at=started_at,
                    completed_at=completed_at,
                )
                db.add(attempt)
                db.flush()

                # Generate responses via IRT response model
                responses_in_order: list[QuizResponse] = []
                correct_count = 0

                for q in selected_q:
                    skill = topic_skills[q.topic_id]
                    p_corr = compute_p_correct(skill, q.difficulty)
                    is_correct = (rng.random() < p_corr)

                    if is_correct:
                        correct_count += 1
                        selected_ans = q.correct_answer
                    else:
                        wrong_opts = [opt for opt in ["A", "B", "C", "D"] if opt != q.correct_answer]
                        selected_ans = rng.choice(wrong_opts)

                    resp = QuizResponse(
                        attempt_id=attempt.id,
                        question_id=q.id,
                        topic_id=q.topic_id,
                        selected_answer=selected_ans,
                        is_correct=is_correct,
                    )
                    db.add(resp)
                    responses_in_order.append(resp)

                attempt.score = correct_count
                db.flush()

                # Raise topic skill slightly after consecutive attempt (+0.03, capped at 0.95)
                for t_id in c_topic_ids:
                    topic_skills[t_id] = min(0.95, topic_skills[t_id] + 0.03)

                # Persist topic mastery and history via canonical apply_attempt
                apply_attempt(
                    db,
                    user.id,
                    attempt,
                    responses_in_order,
                    as_of=completed_at
                )
                db.flush()

                stats["attempts_created"] += 1
                stats["responses_created"] += len(responses_in_order)
                stats["group_stats"][group_key]["attempts"] += 1
                stats["group_stats"][group_key]["total_responses"] += len(responses_in_order)
                stats["group_stats"][group_key]["correct_responses"] += correct_count

            # Tally learner mastery records
            mastery_records = (
                db.query(TopicMastery)
                .filter(TopicMastery.user_id == user.id)
                .all()
            )
            history_records = (
                db.query(TopicMasteryHistory)
                .filter(TopicMasteryHistory.user_id == user.id)
                .all()
            )

            stats["mastery_rows_created"] += len(mastery_records)
            stats["history_rows_created"] += len(history_records)
            stats["learners_created"] += 1
            stats["group_stats"][group_key]["learners"] += 1

            # Map existing mastery rows by topic_id
            mastery_by_topic_id = {m.topic_id: m for m in mastery_records}

            # Check all platform topics for this learner to capture not_attempted
            for c_title, c_obj in courses_by_title.items():
                for t in topics_by_course_id[c_obj.id]:
                    if t.id in mastery_by_topic_id:
                        m = mastery_by_topic_id[t.id]
                        st = classify(m.mastery_probability, m.total_answers)
                        stats["overall_statuses"][st] += 1
                        stats["group_stats"][group_key]["statuses"][st] += 1
                        stats["group_stats"][group_key]["mastery_sum"] += m.mastery_probability
                        stats["group_stats"][group_key]["mastery_count"] += 1
                        stats["group_stats"][group_key]["course_mastery"][c_title].append(
                            m.mastery_probability
                        )
                    else:
                        stats["overall_statuses"]["not_attempted"] += 1
                        stats["group_stats"][group_key]["statuses"]["not_attempted"] += 1

            if dry_run:
                db.rollback()
            else:
                db.commit()

        except Exception as e:
            db.rollback()
            print(f"ERROR: Failed processing synthetic learner {email}: {e}")
            raise

    # 5. Print comprehensive summary
    print(f"\n{mode_str}=== Synthetic Population Seeding Summary ===")
    print(f"Learners Created  : {stats['learners_created']}")
    print(f"Learners Skipped  : {stats['learners_skipped']}")
    print(f"Total Attempts    : {stats['attempts_created']}")
    print(f"Total Responses   : {stats['responses_created']}")
    print(f"Mastery Rows      : {stats['mastery_rows_created']}")
    print(f"History Rows      : {stats['history_rows_created']}")

    print("\n--- Overall Competency Status Distribution ---")
    total_st = sum(stats["overall_statuses"].values())
    for st, count in stats["overall_statuses"].items():
        pct = (count / total_st * 100.0) if total_st > 0 else 0.0
        print(f"  {st:15s}: {count:4d} ({pct:5.1f}%)")

    print("\n--- Per-Group Archetype Differentiation ---")
    for g_key in GROUP_KEYS:
        g_data = stats["group_stats"][g_key]
        arch = ARCHETYPES[g_key]
        avg_m = (
            (g_data["mastery_sum"] / g_data["mastery_count"])
            if g_data["mastery_count"] > 0
            else 0.0
        )
        total_resp = g_data["total_responses"]
        corr_resp = g_data["correct_responses"]
        acc = (corr_resp / total_resp) if total_resp > 0 else 0.0

        print(f"\n[{g_key}] {arch['name']} (Learners: {g_data['learners']}, Attempts: {g_data['attempts']})")
        print(f"    Accuracy       : {acc:.4f} ({corr_resp}/{total_resp})")
        print(f"    Average Mastery: {avg_m:.4f}")
        st_parts = [
            f"{s}: {g_data['statuses'][s]}"
            for s in ["not_attempted", "weak", "developing", "strong"]
        ]
        print(f"    Statuses       : {', '.join(st_parts)}")
        course_parts = []
        for c_name in REQUIRED_COURSE_TITLES:
            probs = g_data["course_mastery"][c_name]
            c_avg = (sum(probs) / len(probs)) if probs else 0.0
            course_parts.append(f"{c_name}: {c_avg:.3f}")
        print(f"    Per-Course Avg : {', '.join(course_parts)}")

    print(f"\n===================================================\n")
    return stats


def main():
    parser = argparse.ArgumentParser(description="LearnWise Synthetic Learners Seeding")
    parser.add_argument(
        "--learners",
        type=int,
        default=50,
        help="Number of synthetic learners to generate (default: 50)"
    )
    parser.add_argument(
        "--learners-per-group",
        type=int,
        default=None,
        help="Number of synthetic learners per archetype group (overrides --learners if set)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without committing changes to database"
    )
    parser.add_argument(
        "--reset-synthetic",
        action="store_true",
        help="Delete all existing synthetic learners (@synthetic.learnwise.test)"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion when using --reset-synthetic"
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_synthetic_learners(
            db=db,
            num_learners=args.learners,
            learners_per_group=args.learners_per_group,
            dry_run=args.dry_run,
            reset_synthetic=args.reset_synthetic,
            confirm_yes=args.yes,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
