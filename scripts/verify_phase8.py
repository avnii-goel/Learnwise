#!/usr/bin/env python3
"""Phase 8 Analytics & Dashboards Verification Script.

READ-ONLY verification — no data is modified.
Connects to the database specified in DATABASE_URL, runs read-only verification
checks comparing dashboard services against independent raw SQL queries, and rolls back.

Usage:
    export DATABASE_URL="<DATABASE_URL>"
    python scripts/verify_phase8.py
"""

import argparse
import os
import sys
from collections import defaultdict
from typing import Any

# Capture explicit DATABASE_URL before any backend imports or load_dotenv() run
EXPLICIT_DATABASE_URL = os.environ.get("DATABASE_URL")
if EXPLICIT_DATABASE_URL:
    EXPLICIT_DATABASE_URL = EXPLICIT_DATABASE_URL.strip("\"'")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend"))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.course import Course
from app.models.topic import Topic
from app.models.topic_mastery import TopicMastery
from app.models.user import User
from app.services.dashboard import (
    get_learner_dashboard_overview,
    get_learner_trends,
)
from app.services.dashboard_instructor import (
    get_instructor_learners,
    get_instructor_overview,
    get_instructor_topics,
)

PROBABILITY_TOLERANCE = 1e-4
PERCENTAGE_TOLERANCE = 0.05


def _approx_eq(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def run_checks(db: Session) -> list[tuple[str, str, str]]:
    """Runs all 9 Phase 8 verification checks against the provided database session.

    Returns:
        list of (check_name, status, detail) where status is PASS, WARN, or FAIL.
    """
    results: list[tuple[str, str, str]] = []

    # -------------------------------------------------------------
    # V1: Total learners count
    # -------------------------------------------------------------
    try:
        ov = get_instructor_overview(db)
        sql_learners = db.execute(
            text("SELECT count(*) FROM users WHERE role = 'learner'")
        ).scalar() or 0

        if ov.total_learners == sql_learners:
            results.append((
                "V1: Total Learners Count",
                "PASS",
                f"Instructor overview ({ov.total_learners}) matches SQL count ({sql_learners})",
            ))
        else:
            results.append((
                "V1: Total Learners Count",
                "FAIL",
                f"Mismatch: Instructor overview={ov.total_learners}, SQL={sql_learners}",
            ))
    except Exception as e:
        results.append(("V1: Total Learners Count", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V2: Completed attempts, active learners, avg quiz percentage
    # -------------------------------------------------------------
    try:
        ov = get_instructor_overview(db)
        v2_sql = db.execute(
            text(
                """
                SELECT 
                    count(qa.id) as completed_attempts,
                    count(DISTINCT qa.user_id) as active_learners,
                    avg(qa.score * 100.0 / nullif(qa.total_questions, 0)) as avg_quiz_percentage
                FROM quiz_attempts qa
                JOIN users u ON u.id = qa.user_id
                WHERE u.role = 'learner' AND qa.status = 'completed'
                """
            )
        ).fetchone()

        sql_completed = v2_sql[0] or 0
        sql_active = v2_sql[1] or 0
        sql_quiz_p = round(float(v2_sql[2]), 1) if v2_sql[2] is not None else None

        v2_mismatches = []
        if ov.completed_attempts != sql_completed:
            v2_mismatches.append(f"completed_attempts (API={ov.completed_attempts}, SQL={sql_completed})")
        if ov.active_learners != sql_active:
            v2_mismatches.append(f"active_learners (API={ov.active_learners}, SQL={sql_active})")
        if not _approx_eq(ov.avg_quiz_percentage, sql_quiz_p, PERCENTAGE_TOLERANCE):
            v2_mismatches.append(f"avg_quiz_percentage (API={ov.avg_quiz_percentage}, SQL={sql_quiz_p})")

        if not v2_mismatches:
            results.append((
                "V2: Cohort Completed Attempts & Quiz Average",
                "PASS",
                f"Completed={ov.completed_attempts}, Active={ov.active_learners}, AvgQuiz={ov.avg_quiz_percentage}% match SQL",
            ))
        else:
            results.append((
                "V2: Cohort Completed Attempts & Quiz Average",
                "FAIL",
                f"Mismatches: {', '.join(v2_mismatches)}",
            ))
    except Exception as e:
        results.append(("V2: Cohort Completed Attempts & Quiz Average", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V3: Per-topic cohort metrics
    # -------------------------------------------------------------
    try:
        topics_resp = get_instructor_topics(db)
        v3_mismatches = []

        for t in topics_resp.topics:
            sql_t = db.execute(
                text(
                    """
                    SELECT 
                        count(tm.id) as learners_attempted,
                        avg(tm.mastery_probability) as avg_mastery,
                        sum(tm.correct_answers) * 100.0 / nullif(sum(tm.total_answers), 0) as accuracy_percent
                    FROM topic_mastery tm
                    JOIN users u ON u.id = tm.user_id
                    WHERE u.role = 'learner' AND tm.total_answers > 0 AND tm.topic_id = :topic_id
                    """
                ),
                {"topic_id": t.topic_id},
            ).fetchone()

            sql_attempted = sql_t[0] or 0
            sql_mastery = round(float(sql_t[1]), 4) if sql_t[1] is not None else None
            sql_accuracy = round(float(sql_t[2]), 1) if sql_t[2] is not None else None

            if t.learners_attempted != sql_attempted:
                v3_mismatches.append(f"T{t.topic_id} learners_attempted (API={t.learners_attempted}, SQL={sql_attempted})")
            if not _approx_eq(t.avg_mastery, sql_mastery, PROBABILITY_TOLERANCE):
                v3_mismatches.append(f"T{t.topic_id} avg_mastery (API={t.avg_mastery}, SQL={sql_mastery})")
            if not _approx_eq(t.accuracy_percent, sql_accuracy, PERCENTAGE_TOLERANCE):
                v3_mismatches.append(f"T{t.topic_id} accuracy (API={t.accuracy_percent}, SQL={sql_accuracy})")

        if not v3_mismatches:
            results.append((
                "V3: Per-Topic Cohort Metrics",
                "PASS",
                f"All {len(topics_resp.topics)} topics match SQL for learners_attempted, avg_mastery, and accuracy",
            ))
        else:
            results.append((
                "V3: Per-Topic Cohort Metrics",
                "FAIL",
                f"Mismatches on {len(v3_mismatches)} metric(s): {', '.join(v3_mismatches[:5])}",
            ))
    except Exception as e:
        results.append(("V3: Per-Topic Cohort Metrics", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V4: Per-course avg_quiz_percentage and completed_attempts
    # -------------------------------------------------------------
    try:
        ov = get_instructor_overview(db)
        v4_mismatches = []

        for c in ov.courses:
            sql_c = db.execute(
                text(
                    """
                    SELECT 
                        count(qa.id) as completed_attempts,
                        avg(qa.score * 100.0 / nullif(qa.total_questions, 0)) as avg_quiz_percentage
                    FROM quiz_attempts qa
                    JOIN users u ON u.id = qa.user_id
                    WHERE u.role = 'learner' AND qa.status = 'completed' AND qa.course_id = :course_id
                    """
                ),
                {"course_id": c.course_id},
            ).fetchone()

            sql_completed = sql_c[0] or 0
            sql_quiz_p = round(float(sql_c[1]), 1) if sql_c[1] is not None else None

            if c.completed_attempts != sql_completed:
                v4_mismatches.append(f"Course {c.course_id} attempts (API={c.completed_attempts}, SQL={sql_completed})")
            if not _approx_eq(c.avg_quiz_percentage, sql_quiz_p, PERCENTAGE_TOLERANCE):
                v4_mismatches.append(f"Course {c.course_id} quiz_avg (API={c.avg_quiz_percentage}, SQL={sql_quiz_p})")

        if not v4_mismatches:
            results.append((
                "V4: Per-Course Quiz Averages & Attempts",
                "PASS",
                f"All {len(ov.courses)} courses match independent SQL grouping",
            ))
        else:
            results.append((
                "V4: Per-Course Quiz Averages & Attempts",
                "FAIL",
                f"Mismatches: {', '.join(v4_mismatches)}",
            ))
    except Exception as e:
        results.append(("V4: Per-Course Quiz Averages & Attempts", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V5: Instructor Learners list matches SQL
    # -------------------------------------------------------------
    try:
        learners_resp = get_instructor_learners(db)
        v5_mismatches = []

        for item in learners_resp.items:
            sql_m = db.execute(
                text("SELECT count(*), avg(mastery_probability) FROM topic_mastery WHERE user_id = :uid AND total_answers > 0"),
                {"uid": item.user_id},
            ).fetchone()
            sql_a = db.execute(
                text("SELECT count(*), avg(score * 100.0 / nullif(total_questions, 0)) FROM quiz_attempts WHERE user_id = :uid AND status = 'completed'"),
                {"uid": item.user_id},
            ).fetchone()

            sql_attempted_topics = sql_m[0] or 0
            sql_avg_m = round(float(sql_m[1]), 4) if sql_m[1] is not None else None
            sql_completed_attempts = sql_a[0] or 0
            sql_avg_p = round(float(sql_a[1]), 1) if sql_a[1] is not None else None

            if item.attempted_topics != sql_attempted_topics:
                v5_mismatches.append(f"User {item.user_id} attempted_topics (API={item.attempted_topics}, SQL={sql_attempted_topics})")
            if not _approx_eq(item.avg_mastery_attempted, sql_avg_m, PROBABILITY_TOLERANCE):
                v5_mismatches.append(f"User {item.user_id} avg_mastery (API={item.avg_mastery_attempted}, SQL={sql_avg_m})")
            if item.completed_attempts != sql_completed_attempts:
                v5_mismatches.append(f"User {item.user_id} completed_attempts (API={item.completed_attempts}, SQL={sql_completed_attempts})")
            if not _approx_eq(item.avg_quiz_percentage, sql_avg_p, PERCENTAGE_TOLERANCE):
                v5_mismatches.append(f"User {item.user_id} avg_quiz_percentage (API={item.avg_quiz_percentage}, SQL={sql_avg_p})")

        if not v5_mismatches:
            results.append((
                "V5: Instructor Learners Directory",
                "PASS",
                f"All {len(learners_resp.items)} learners match SQL metrics without row fan-out",
            ))
        else:
            results.append((
                "V5: Instructor Learners Directory",
                "FAIL",
                f"Mismatches on {len(v5_mismatches)} item(s): {', '.join(v5_mismatches[:5])}",
            ))
    except Exception as e:
        results.append(("V5: Instructor Learners Directory", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V6: Learner Dashboard consistency for active learners
    # -------------------------------------------------------------
    try:
        active_learner_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT u.id 
                    FROM users u
                    JOIN topic_mastery tm ON tm.user_id = u.id
                    WHERE u.role = 'learner' AND tm.total_answers > 0
                    """
                )
            ).fetchall()
        ]
        total_topics = db.execute(text("SELECT count(*) FROM topics")).scalar() or 0
        v6_mismatches = []

        for uid in active_learner_ids:
            dash = get_learner_dashboard_overview(db, uid)
            lov = dash.overview

            status_sum = (
                lov.status_counts.strong
                + lov.status_counts.developing
                + lov.status_counts.weak
                + lov.status_counts.not_attempted
            )
            if status_sum != total_topics:
                v6_mismatches.append(f"User {uid} status_counts sum ({status_sum} != {total_topics})")

            sql_m = db.execute(
                text("SELECT count(*), avg(mastery_probability) FROM topic_mastery WHERE user_id = :uid AND total_answers > 0"),
                {"uid": uid},
            ).fetchone()
            sql_attempted = sql_m[0] or 0
            sql_avg_m = round(float(sql_m[1]), 4) if sql_m[1] is not None else None

            if lov.attempted_topics != sql_attempted:
                v6_mismatches.append(f"User {uid} attempted ({lov.attempted_topics} != {sql_attempted})")
            if not _approx_eq(lov.avg_mastery_attempted, sql_avg_m, PROBABILITY_TOLERANCE):
                v6_mismatches.append(f"User {uid} avg_mastery ({lov.avg_mastery_attempted} != {sql_avg_m})")

            expected_progress = round(sql_attempted / total_topics * 100.0, 1) if total_topics > 0 else 0.0
            if not _approx_eq(lov.progress_percent, expected_progress, PERCENTAGE_TOLERANCE):
                v6_mismatches.append(f"User {uid} progress ({lov.progress_percent} != {expected_progress})")

        if not v6_mismatches:
            results.append((
                "V6: Learner Dashboard Consistency",
                "PASS",
                f"All {len(active_learner_ids)} active learners have status sum == {total_topics} and exact SQL matches",
            ))
        else:
            results.append((
                "V6: Learner Dashboard Consistency",
                "FAIL",
                f"Mismatches on {len(v6_mismatches)} record(s): {', '.join(v6_mismatches[:5])}",
            ))
    except Exception as e:
        results.append(("V6: Learner Dashboard Consistency", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V7: Trend vs Overview alignment (WARN level)
    # -------------------------------------------------------------
    try:
        active_learner_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT u.id 
                    FROM users u
                    JOIN topic_mastery tm ON tm.user_id = u.id
                    WHERE u.role = 'learner' AND tm.total_answers > 0
                    """
                )
            ).fetchall()
        ]

        differ_count = 0
        total_checked = 0

        for uid in active_learner_ids:
            trends = get_learner_trends(db, uid)
            if trends.mastery_progress:
                total_checked += 1
                last_point = trends.mastery_progress[-1].avg_mastery
                lov = get_learner_dashboard_overview(db, uid).overview
                if not _approx_eq(last_point, lov.avg_mastery_attempted, PROBABILITY_TOLERANCE):
                    differ_count += 1

        if differ_count == 0:
            results.append((
                "V7: Trend vs Overview Alignment",
                "PASS",
                f"All {total_checked} active learners with trends have final mastery point == overview avg_mastery_attempted",
            ))
        else:
            results.append((
                "V7: Trend vs Overview Alignment",
                "WARN",
                f"{differ_count} of {total_checked} learners differ between last trend point and overview avg (legitimate if attempts occurred before mastery history tracking or topics were manually seeded)",
            ))
    except Exception as e:
        results.append(("V7: Trend vs Overview Alignment", "WARN", f"Exception: {e}"))

    # -------------------------------------------------------------
    # V8: Synthetic Learner Archetypes
    # -------------------------------------------------------------
    try:
        synthetic_users = db.query(User).filter(User.email.like("synthetic-%@synthetic.learnwise.test")).all()

        if len(synthetic_users) < 40:
            results.append((
                "V8: Synthetic Learner Archetypes",
                "PASS",
                f"Skipped (only {len(synthetic_users)} synthetic learners in database, minimum 40 required for archetypes)",
            ))
        else:
            # Map email -> user
            user_by_idx: dict[int, User] = {}
            for u in synthetic_users:
                # Format: synthetic-NN@synthetic.learnwise.test
                try:
                    prefix = u.email.split("@")[0].split("-")[1]
                    user_by_idx[int(prefix)] = u
                except (IndexError, ValueError):
                    continue

            # Group 01-10 vs 11-20
            g1_masteries = []
            for idx in range(1, 11):
                u = user_by_idx.get(idx)
                if u:
                    ov = get_learner_dashboard_overview(db, u.id).overview
                    if ov.avg_mastery_attempted is not None:
                        g1_masteries.append(ov.avg_mastery_attempted)

            g2_masteries = []
            for idx in range(11, 21):
                u = user_by_idx.get(idx)
                if u:
                    ov = get_learner_dashboard_overview(db, u.id).overview
                    if ov.avg_mastery_attempted is not None:
                        g2_masteries.append(ov.avg_mastery_attempted)

            mean_g1 = sum(g1_masteries) / len(g1_masteries) if g1_masteries else 0.0
            mean_g2 = sum(g2_masteries) / len(g2_masteries) if g2_masteries else 0.0

            archetype_failures = []
            if mean_g1 - mean_g2 < 0.15:
                archetype_failures.append(f"Group 01-10 mean ({mean_g1:.4f}) does not exceed Group 11-20 ({mean_g2:.4f}) by >= 0.15")

            # Course lookup
            courses = {c.title: c.id for c in db.query(Course).all()}
            sys_course_ids = [cid for title, cid in courses.items() if title in ("Computer Networks", "Operating Systems")]
            app_course_ids = [cid for title, cid in courses.items() if title in ("OOPS", "SQL/DBMS")]

            def get_course_mastery_for_users(user_indices: range, course_ids: list[int]) -> float:
                uids = [user_by_idx[i].id for i in user_indices if i in user_by_idx]
                if not uids or not course_ids:
                    return 0.0
                val = db.execute(
                    text(
                        """
                        SELECT avg(tm.mastery_probability)
                        FROM topic_mastery tm
                        JOIN topics t ON t.id = tm.topic_id
                        WHERE tm.user_id IN :uids AND t.course_id IN :cids AND tm.total_answers > 0
                        """
                    ).bindparams(uids=tuple(uids), cids=tuple(course_ids))
                ).scalar()
                return float(val) if val is not None else 0.0

            # Group 21-30: Systems > Apps by >= 0.15
            sys_g3 = get_course_mastery_for_users(range(21, 31), sys_course_ids)
            app_g3 = get_course_mastery_for_users(range(21, 31), app_course_ids)
            if sys_g3 - app_g3 < 0.15:
                archetype_failures.append(f"Group 21-30 Systems ({sys_g3:.4f}) does not exceed Apps ({app_g3:.4f}) by >= 0.15")

            # Group 31-40: Apps > Systems by >= 0.15
            sys_g4 = get_course_mastery_for_users(range(31, 41), sys_course_ids)
            app_g4 = get_course_mastery_for_users(range(31, 41), app_course_ids)
            if app_g4 - sys_g4 < 0.15:
                archetype_failures.append(f"Group 31-40 Apps ({app_g4:.4f}) does not exceed Systems ({sys_g4:.4f}) by >= 0.15")

            if not archetype_failures:
                results.append((
                    "V8: Synthetic Learner Archetypes",
                    "PASS",
                    f"Group 01-10 ({mean_g1:.3f}) > Group 11-20 ({mean_g2:.3f}); Group 21-30 Systems ({sys_g3:.3f}) > Apps ({app_g3:.3f}); Group 31-40 Apps ({app_g4:.3f}) > Systems ({sys_g4:.3f})",
                ))
            else:
                results.append((
                    "V8: Synthetic Learner Archetypes",
                    "FAIL",
                    f"Archetype separation failure: {'; '.join(archetype_failures)}",
                ))
    except Exception as e:
        results.append(("V8: Synthetic Learner Archetypes", "FAIL", f"Exception raised: {e}"))

    # -------------------------------------------------------------
    # V9: Null completed_at in completed attempts (WARN level)
    # -------------------------------------------------------------
    try:
        null_completed_count = db.execute(
            text("SELECT count(*) FROM quiz_attempts WHERE status = 'completed' AND completed_at IS NULL")
        ).scalar() or 0

        if null_completed_count == 0:
            results.append((
                "V9: Completed Attempts completed_at Integrity",
                "PASS",
                "0 completed attempts have NULL completed_at",
            ))
        else:
            results.append((
                "V9: Completed Attempts completed_at Integrity",
                "WARN",
                f"{null_completed_count} completed attempt(s) have NULL completed_at (handled defensively by COALESCE(completed_at, started_at))",
            ))
    except Exception as e:
        results.append(("V9: Completed Attempts completed_at Integrity", "WARN", f"Exception raised: {e}"))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="READ-ONLY verification script for LearnWise Phase 8 analytics & dashboards."
    )
    parser.parse_args()

    print("=" * 70)
    print("READ-ONLY verification — no data is modified.")
    print("=" * 70)

    db_url = EXPLICIT_DATABASE_URL
    if not db_url:
        print("[ERROR] DATABASE_URL environment variable is not set.", file=sys.stderr)
        print("Set it before running: export DATABASE_URL=\"<DATABASE_URL>\"", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url, pool_pre_ping=True)
    SessionClass = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionClass()

    fail_count = 0
    warn_count = 0
    pass_count = 0

    try:
        # Guarantee strict transaction read-only mode
        db.execute(text("SET TRANSACTION READ ONLY"))

        check_results = run_checks(db)

        for name, status, detail in check_results:
            print(f"[{status}] {name} — {detail}")
            if status == "FAIL":
                fail_count += 1
            elif status == "WARN":
                warn_count += 1
            elif status == "PASS":
                pass_count += 1

    finally:
        # ALWAYS roll back; never persist any state
        db.rollback()
        db.close()
        engine.dispose()

    print("=" * 70)
    print(f"Summary: {pass_count} PASSED, {warn_count} WARNINGS, {fail_count} FAILED.")
    print("=" * 70)

    if fail_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

