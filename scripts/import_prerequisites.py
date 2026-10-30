#!/usr/bin/env python3
"""Topic prerequisite import script for LearnWise.

Imports directed prerequisite relations between topics within the same course.
Enforces all-or-nothing validation, same-course restrictions, self-loop bans,
and global cycle detection across file edges and existing database records.

Usage:
    python scripts/import_prerequisites.py --file data/topic_prerequisites_draft.csv [--dry-run]
"""

import argparse
import collections
import csv
import os
import sys
from typing import Any

# Ensure backend directory is in sys.path and load environment
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.course import Course
from app.models.topic import Topic
from app.models.topic_prerequisite import TopicPrerequisite

EXPECTED_HEADER = [
    "course_title",
    "topic_title",
    "prerequisite_topic_title",
]


def detect_cycle(edges: set[tuple[int, int]]) -> list[int] | None:
    """Detects any directed cycle in the given edge set (u -> v).

    Returns:
        list[int] | None: Ordered node IDs forming a cycle (e.g. [A, B, C, A]), or None if DAG.
    """
    adj: dict[int, list[int]] = collections.defaultdict(list)
    nodes: set[int] = set()
    for u, v in edges:
        adj[u].append(v)
        nodes.add(u)
        nodes.add(v)

    # 0 = unvisited, 1 = visiting (in active path), 2 = fully visited
    state: dict[int, int] = {}
    path: list[int] = []

    def dfs(u: int) -> list[int] | None:
        state[u] = 1
        path.append(u)
        for v in adj.get(u, []):
            if state.get(v, 0) == 1:
                # Cycle identified
                cycle_start = path.index(v)
                return path[cycle_start:] + [v]
            elif state.get(v, 0) == 0:
                res = dfs(v)
                if res is not None:
                    return res
        path.pop()
        state[u] = 2
        return None

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            cycle = dfs(node)
            if cycle is not None:
                return cycle
    return None


def print_error_table(errors: list[dict[str, Any]]) -> None:
    """Prints validation errors formatted in an ASCII table."""
    if not errors:
        return
    headers = ["Row", "Field", "Error"]
    row_col = [str(e.get("row", "")) for e in errors]
    field_col = [str(e.get("field", "")) for e in errors]
    err_col = [str(e.get("error", "")) for e in errors]

    w_row = max(len(headers[0]), max((len(r) for r in row_col), default=0))
    w_field = max(len(headers[1]), max((len(f) for f in field_col), default=0))
    w_err = max(len(headers[2]), max((len(err) for err in err_col), default=0))

    sep = f"+-{'-' * w_row}-+-{'-' * w_field}-+-{'-' * w_err}-+"
    print("\nValidation Errors:")
    print(sep)
    print(f"| {headers[0].ljust(w_row)} | {headers[1].ljust(w_field)} | {headers[2].ljust(w_err)} |")
    print(sep)
    for r, f, err in zip(row_col, field_col, err_col):
        print(f"| {r.rjust(w_row)} | {f.ljust(w_field)} | {err.ljust(w_err)} |")
    print(sep + "\n")


def import_prerequisites(
    db: Session,
    file_path: str,
    dry_run: bool = False
) -> dict[str, Any]:
    """Validates and imports topic prerequisites from CSV.

    All-or-nothing: validates every row, checks course constraints, self-loops,
    file duplicates, and verifies acyclicity against combined DB + file graph.

    Returns:
        dict: {
            "inserted": int,
            "unchanged": int,
            "errors": list[dict],
            "dry_run": bool
        }
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prerequisite file not found: {file_path}")

    # 1. Read CSV file
    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            raw_header = next(reader)
        except StopIteration:
            return {
                "inserted": 0,
                "unchanged": 0,
                "errors": [{"row": 1, "field": "header", "error": "CSV file is empty"}],
                "dry_run": dry_run,
            }

        header = [col.strip() for col in raw_header]
        if header != EXPECTED_HEADER:
            return {
                "inserted": 0,
                "unchanged": 0,
                "errors": [{
                    "row": 1,
                    "field": "header",
                    "error": f"Invalid header. Expected {EXPECTED_HEADER}, got {header}"
                }],
                "dry_run": dry_run,
            }

        rows = list(reader)

    # 2. Database lookups
    courses = db.query(Course).all()
    course_map = {c.title.strip().lower(): c for c in courses}

    topics = db.query(Topic).all()
    # Map (course_id, topic_title_lower) -> Topic
    topic_map = {(t.course_id, t.title.strip().lower()): t for t in topics}
    # ID to topic
    topic_id_to_topic = {t.id: t for t in topics}
    # Topic title to list of Topics
    topic_by_title: dict[str, list[Topic]] = {}
    for t in topics:
        topic_by_title.setdefault(t.title.strip().lower(), []).append(t)

    # Query existing DB edges
    existing_edges = set(
        db.query(TopicPrerequisite.topic_id, TopicPrerequisite.prerequisite_topic_id).all()
    )

    # 3. Validate every row
    errors: list[dict[str, Any]] = []
    file_edges: list[tuple[int, int, int]] = []  # (topic_id, prereq_topic_id, row_idx)
    seen_file_edges: dict[tuple[int, int], int] = {}  # edge -> first_row

    for line_idx, raw_row in enumerate(rows, start=2):
        if not raw_row or not any(cell.strip() for cell in raw_row):
            continue

        if len(raw_row) != len(EXPECTED_HEADER):
            errors.append({
                "row": line_idx,
                "field": "row",
                "error": f"Expected {len(EXPECTED_HEADER)} columns, got {len(raw_row)}"
            })
            continue

        course_title_raw = raw_row[0].strip()
        topic_title_raw = raw_row[1].strip()
        prereq_title_raw = raw_row[2].strip()

        # (a) Course existence
        course = course_map.get(course_title_raw.lower())
        if not course:
            errors.append({
                "row": line_idx,
                "field": "course_title",
                "error": f"Course '{course_title_raw}' does not exist"
            })

        # (b) Topic existence
        topic = None
        prereq_topic = None

        if course:
            topic = topic_map.get((course.id, topic_title_raw.lower()))
            if not topic:
                if topic_title_raw.lower() in topic_by_title:
                    errors.append({
                        "row": line_idx,
                        "field": "topic_title",
                        "error": f"Topic '{topic_title_raw}' does not belong to course '{course_title_raw}'"
                    })
                else:
                    errors.append({
                        "row": line_idx,
                        "field": "topic_title",
                        "error": f"Topic '{topic_title_raw}' does not exist"
                    })

            prereq_topic = topic_map.get((course.id, prereq_title_raw.lower()))
            if not prereq_topic:
                if prereq_title_raw.lower() in topic_by_title:
                    errors.append({
                        "row": line_idx,
                        "field": "prerequisite_topic_title",
                        "error": (
                            f"Prerequisite topic '{prereq_title_raw}' does not belong "
                            f"to course '{course_title_raw}'"
                        )
                    })
                else:
                    errors.append({
                        "row": line_idx,
                        "field": "prerequisite_topic_title",
                        "error": f"Prerequisite topic '{prereq_title_raw}' does not exist"
                    })
        else:
            # Check topics generally
            if topic_title_raw.lower() not in topic_by_title:
                errors.append({
                    "row": line_idx,
                    "field": "topic_title",
                    "error": f"Topic '{topic_title_raw}' does not exist"
                })
            if prereq_title_raw.lower() not in topic_by_title:
                errors.append({
                    "row": line_idx,
                    "field": "prerequisite_topic_title",
                    "error": f"Prerequisite topic '{prereq_title_raw}' does not exist"
                })

        # (c) Self-loop check
        if topic and prereq_topic and topic.id == prereq_topic.id:
            errors.append({
                "row": line_idx,
                "field": "prerequisite_topic_title",
                "error": f"Self-loop: topic '{topic_title_raw}' cannot require itself"
            })
            continue

        # (d) Duplicate edge in file
        if topic and prereq_topic:
            edge = (topic.id, prereq_topic.id)
            if edge in seen_file_edges:
                first_row = seen_file_edges[edge]
                errors.append({
                    "row": line_idx,
                    "field": "edge",
                    "error": (
                        f"Duplicate prerequisite edge in file: '{topic_title_raw}' -> "
                        f"'{prereq_title_raw}' already seen on row {first_row}"
                    )
                })
            else:
                seen_file_edges[edge] = line_idx
                file_edges.append((topic.id, prereq_topic.id, line_idx))

    # (e) Cycle detection (combining file edges + existing DB edges)
    # Only evaluate cycle if no previous per-row errors
    if not errors and file_edges:
        combined_edges = set(existing_edges)
        for u, v, _ in file_edges:
            combined_edges.add((u, v))

        cycle = detect_cycle(combined_edges)
        if cycle:
            # Format cycle titles
            cycle_titles = [
                topic_id_to_topic[nid].title if nid in topic_id_to_topic else str(nid)
                for nid in cycle
            ]
            cycle_str = " -> ".join(cycle_titles)
            errors.append({
                "row": "Graph",
                "field": "cycle",
                "error": f"Cycle detected in prerequisite graph: {cycle_str}"
            })

    # Abort if any errors
    if errors:
        return {
            "inserted": 0,
            "unchanged": 0,
            "errors": errors,
            "dry_run": dry_run,
        }

    # 4. Insert or recognize unchanged
    inserted_count = 0
    unchanged_count = 0

    for u, v, _ in file_edges:
        edge = (u, v)
        if edge in existing_edges:
            unchanged_count += 1
        else:
            new_prereq = TopicPrerequisite(
                topic_id=u,
                prerequisite_topic_id=v
            )
            db.add(new_prereq)
            existing_edges.add(edge)
            inserted_count += 1

    # 5. Commit or Rollback
    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "inserted": inserted_count,
        "unchanged": unchanged_count,
        "errors": [],
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="LearnWise Topic Prerequisite Import Script")
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the prerequisites CSV file (e.g. data/topic_prerequisites_draft.csv)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate import without persisting changes to the database"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = import_prerequisites(db, args.file, dry_run=args.dry_run)

        if result["errors"]:
            print_error_table(result["errors"])
            print("Import aborted: all-or-nothing validation failed. No changes were made.")
            sys.exit(1)

        mode_str = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{mode_str}=== LearnWise Topic Prerequisite Import Summary ===")
        print(f"File      : {args.file}")
        print(f"Mode      : {'Dry Run (Simulated)' if args.dry_run else 'Live Commit'}")
        print(f"Inserted  : {result['inserted']}")
        print(f"Unchanged : {result['unchanged']}")
        print("====================================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()

