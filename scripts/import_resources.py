#!/usr/bin/env python3
"""Curated learning resource import script for LearnWise.

Imports resources from CSV into the learning_resources table with all-or-nothing
validation, idempotency, and update-vs-insert semantics.

Usage:
    python scripts/import_resources.py --file data/resources.csv [--dry-run]
"""

import argparse
import csv
import os
import sys
import urllib.parse
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
from app.models.learningresource import LearningResource, ALLOWED_RESOURCE_TYPES

EXPECTED_HEADER = [
    "course_title",
    "topic_title",
    "title",
    "description",
    "resource_type",
    "url",
    "difficulty",
    "order",
]

ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}


def normalize_url(url: str) -> str:
    """Normalizes URL by stripping whitespace, lowercasing scheme/host, and normalizing path."""
    cleaned = url.strip()
    parsed = urllib.parse.urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))


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


def import_resources(
    db: Session,
    file_path: str,
    dry_run: bool = False
) -> dict[str, Any]:
    """Validates and imports learning resources from CSV.

    All-or-nothing: every row is validated before any database changes are made.
    Existing (topic_id, url) rows are updated (preserving embeddings); new ones inserted.

    Returns:
        dict: {
            "inserted": int,
            "updated": int,
            "unchanged": int,
            "warnings": list[str],
            "errors": list[dict],
            "dry_run": bool
        }
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Resource file not found: {file_path}")

    # 1. Read CSV file
    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            raw_header = next(reader)
        except StopIteration:
            return {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "warnings": [],
                "errors": [{"row": 1, "field": "header", "error": "CSV file is empty"}],
                "dry_run": dry_run,
            }

        header = [col.strip() for col in raw_header]
        if header != EXPECTED_HEADER:
            return {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "warnings": [],
                "errors": [{
                    "row": 1,
                    "field": "header",
                    "error": f"Invalid header. Expected {EXPECTED_HEADER}, got {header}"
                }],
                "dry_run": dry_run,
            }

        rows = list(reader)

    # 2. Build in-memory lookup cache from database
    courses = db.query(Course).all()
    # Case-insensitive map: course_title_lower -> Course
    course_map = {c.title.strip().lower(): c for c in courses}

    topics = db.query(Topic).all()
    # Map (course_id, topic_title_lower) -> Topic
    topic_map = {(t.course_id, t.title.strip().lower()): t for t in topics}
    # General topic title map to detect wrong course: topic_title_lower -> list of Topics
    topic_by_title: dict[str, list[Topic]] = {}
    for t in topics:
        topic_by_title.setdefault(t.title.strip().lower(), []).append(t)

    # Query existing resources in DB: (topic_id, normalized_url) -> LearningResource
    existing_resources = db.query(LearningResource).all()
    db_resource_map: dict[tuple[int, str], LearningResource] = {}
    for r in existing_resources:
        norm = normalize_url(r.url)
        db_resource_map[(r.topic_id, norm)] = r

    # Query current maximum orders per topic
    topic_orders: dict[int, set[int]] = {}
    for r in existing_resources:
        topic_orders.setdefault(r.topic_id, set()).add(r.order)

    # 3. Validate EVERY row (all-or-nothing)
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    validated_rows: list[dict[str, Any]] = []

    # Duplicate tracking within file:
    # (topic_id, norm_url) -> first row number
    file_seen_topic_urls: dict[tuple[int, str], int] = {}
    # norm_url -> first (topic_title, row_number)
    url_to_topic: dict[str, tuple[str, int]] = {}

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
        title_raw = raw_row[2].strip()
        desc_raw = raw_row[3].strip()
        rtype_raw = raw_row[4].strip().lower()
        url_raw = raw_row[5].strip()
        diff_raw = raw_row[6].strip().lower()
        order_raw = raw_row[7].strip()

        # (a) Course existence
        course = course_map.get(course_title_raw.lower())
        if not course:
            errors.append({
                "row": line_idx,
                "field": "course_title",
                "error": f"Course '{course_title_raw}' does not exist"
            })

        # (b) Topic existence & membership
        topic = None
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
        else:
            # Check if topic exists at all
            if topic_title_raw.lower() not in topic_by_title:
                errors.append({
                    "row": line_idx,
                    "field": "topic_title",
                    "error": f"Topic '{topic_title_raw}' does not exist"
                })

        # (c) Title non-empty
        if not title_raw:
            errors.append({
                "row": line_idx,
                "field": "title",
                "error": "Title cannot be empty"
            })

        # (d) Description at least 30 characters
        if len(desc_raw) < 30:
            errors.append({
                "row": line_idx,
                "field": "description",
                "error": f"Description must be at least 30 characters (got {len(desc_raw)})"
            })

        # (e) Resource type in ALLOWED_RESOURCE_TYPES
        if rtype_raw not in ALLOWED_RESOURCE_TYPES:
            allowed_str = ", ".join(sorted(ALLOWED_RESOURCE_TYPES))
            errors.append({
                "row": line_idx,
                "field": "resource_type",
                "error": f"Invalid resource_type '{rtype_raw}'. Allowed: {allowed_str}"
            })

        # (f) Difficulty in easy, medium, hard
        if diff_raw not in ALLOWED_DIFFICULTIES:
            allowed_diff = ", ".join(sorted(ALLOWED_DIFFICULTIES))
            errors.append({
                "row": line_idx,
                "field": "difficulty",
                "error": f"Invalid difficulty '{diff_raw}'. Allowed: {allowed_diff}"
            })

        # (g) URL starts with http:// or https:// and has host
        parsed_url = urllib.parse.urlsplit(url_raw)
        if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.netloc:
            errors.append({
                "row": line_idx,
                "field": "url",
                "error": "URL must start with http:// or https:// and have a valid host"
            })

        # (h) Order validation
        parsed_order = None
        if order_raw:
            try:
                parsed_order = int(order_raw)
            except ValueError:
                errors.append({
                    "row": line_idx,
                    "field": "order",
                    "error": f"Order must be an integer (got '{order_raw}')"
                })

        # Normalised URL for uniqueness checks
        norm_url = normalize_url(url_raw) if parsed_url.netloc else url_raw

        # (i) File duplicates: same (topic, normalised url) twice is ERROR
        if topic:
            pair = (topic.id, norm_url)
            if pair in file_seen_topic_urls:
                first_row = file_seen_topic_urls[pair]
                errors.append({
                    "row": line_idx,
                    "field": "url",
                    "error": (
                        f"Duplicate (topic, url) in file: topic '{topic_title_raw}' and "
                        f"URL '{url_raw}' already seen on row {first_row}"
                    )
                })
            else:
                file_seen_topic_urls[pair] = line_idx

        # (j) Cross-topic URL: same url under different topics is WARNING
        if norm_url in url_to_topic:
            prev_topic, prev_row = url_to_topic[norm_url]
            if prev_topic.lower() != topic_title_raw.lower():
                warnings.append(
                    f"Row {line_idx}: URL '{url_raw}' under topic '{topic_title_raw}' "
                    f"is also used under topic '{prev_topic}' (row {prev_row})"
                )
        else:
            url_to_topic[norm_url] = (topic_title_raw, line_idx)

        validated_rows.append({
            "row_idx": line_idx,
            "topic": topic,
            "title": title_raw,
            "description": desc_raw,
            "resource_type": rtype_raw,
            "url": url_raw,
            "norm_url": norm_url,
            "difficulty": diff_raw,
            "order": parsed_order,
        })

    # If ANY validation errors occurred, abort without writing anything
    if errors:
        return {
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "warnings": warnings,
            "errors": errors,
            "dry_run": dry_run,
        }

    # 4. Process Inserts and Updates
    inserted_count = 0
    updated_count = 0
    unchanged_count = 0

    for row_info in validated_rows:
        topic = row_info["topic"]
        assert topic is not None
        norm_url = row_info["norm_url"]
        url_to_store = row_info["url"]

        # Determine order if omitted
        existing = db_resource_map.get((topic.id, norm_url))
        if row_info["order"] is not None:
            final_order = row_info["order"]
        elif existing is not None:
            final_order = existing.order
        else:
            used_orders = topic_orders.setdefault(topic.id, set())
            final_order = max(used_orders, default=0) + 1

        topic_orders.setdefault(topic.id, set()).add(final_order)

        if existing is not None:
            # Check for changes in title, description, resource_type, difficulty, order
            is_unchanged = (
                existing.title == row_info["title"]
                and existing.description == row_info["description"]
                and existing.resource_type == row_info["resource_type"]
                and existing.difficulty == row_info["difficulty"]
                and existing.order == final_order
            )
            if is_unchanged:
                unchanged_count += 1
            else:
                existing.title = row_info["title"]
                existing.description = row_info["description"]
                existing.resource_type = row_info["resource_type"]
                existing.difficulty = row_info["difficulty"]
                existing.order = final_order
                # On update, do NOT touch embedding or embedding_hash
                updated_count += 1
        else:
            new_resource = LearningResource(
                topic_id=topic.id,
                title=row_info["title"],
                description=row_info["description"],
                resource_type=row_info["resource_type"],
                url=url_to_store,
                difficulty=row_info["difficulty"],
                order=final_order,
                embedding=None,
                embedding_hash=None,
            )
            db.add(new_resource)
            db_resource_map[(topic.id, norm_url)] = new_resource
            inserted_count += 1

    # 5. Commit or Rollback
    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "inserted": inserted_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
        "warnings": warnings,
        "errors": [],
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="LearnWise Learning Resource Import Script")
    parser.add_argument(
        "--file",
        required=True,
        help="Path to the resources CSV file (e.g. data/resources.csv)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate import without persisting changes to the database"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = import_resources(db, args.file, dry_run=args.dry_run)

        # Print warnings
        for w in result["warnings"]:
            print(f"WARNING: {w}")

        # Handle errors
        if result["errors"]:
            print_error_table(result["errors"])
            print("Import aborted: all-or-nothing validation failed. No changes were made.")
            sys.exit(1)

        # Print summary
        mode_str = "[DRY RUN] " if args.dry_run else ""
        print(f"\n{mode_str}=== LearnWise Resource Import Summary ===")
        print(f"File      : {args.file}")
        print(f"Mode      : {'Dry Run (Simulated)' if args.dry_run else 'Live Commit'}")
        print(f"Inserted  : {result['inserted']}")
        print(f"Updated   : {result['updated']}")
        print(f"Unchanged : {result['unchanged']}")
        print("=========================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()

