"""Tests for learning resource and prerequisite import scripts.

Validates all rules specified in docs/RECOMMENDER.md Section 4 and Chunk 6.2:
- Resource schema validation (course/topic presence, title, description >= 30,
  allowed resource_types, difficulty, valid URL with host, order default).
- Duplicate URL in same topic is an error; across topics is a warning.
- Update vs insert semantics (preserving embedding and embedding_hash on update).
- Dry-run writes nothing.
- Prerequisite validation (both topics exist, same course, self-loops prohibited).
- Prerequisite cycle detection (within file, and combined with DB edges).
- Real data/resources.csv and data/topic_prerequisites_draft.csv validation.
"""

import csv
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# Import scripts
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from scripts.import_resources import import_resources, ALLOWED_RESOURCE_TYPES, normalize_url
from scripts.import_prerequisites import import_prerequisites, detect_cycle
from app.models.course import Course
from app.models.topic import Topic
from app.models.learningresource import LearningResource
from app.models.topic_prerequisite import TopicPrerequisite


def make_csv(path: Path, header: list[str], rows: list[list[str]]) -> str:
    """Helper to write CSV content to a temporary path."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


RESOURCE_HEADER = [
    "course_title",
    "topic_title",
    "title",
    "description",
    "resource_type",
    "url",
    "difficulty",
    "order",
]

PREREQ_HEADER = [
    "course_title",
    "topic_title",
    "prerequisite_topic_title",
]


# ============================================================================
# 1. Real Dataset Verification
# ============================================================================

def test_data_resources_csv_passes_validation(db_session: Session):
    """Validates that repo's data/resources.csv passes full validation against seeded DB."""
    resources_path = os.path.join(repo_root, "data/resources.csv")
    assert os.path.exists(resources_path), "data/resources.csv must exist"

    result = import_resources(db_session, resources_path, dry_run=True)
    assert not result["errors"], f"data/resources.csv had errors: {result['errors']}"
    assert result["inserted"] == 96
    assert result["updated"] == 0
    assert result["unchanged"] == 0


def test_data_topic_prerequisites_draft_csv_passes_validation(db_session: Session):
    """Validates that repo's data/topic_prerequisites_draft.csv passes validation."""
    prereq_path = os.path.join(repo_root, "data/topic_prerequisites_draft.csv")
    assert os.path.exists(prereq_path), "data/topic_prerequisites_draft.csv must exist"

    result = import_prerequisites(db_session, prereq_path, dry_run=True)
    assert not result["errors"], f"draft prerequisites had errors: {result['errors']}"
    assert result["inserted"] == 20
    assert result["unchanged"] == 0


def test_data_prerequisites_csv_passes_validation(db_session: Session):
    """Validates that repo's pruned data/prerequisites.csv passes validation."""
    prereq_path = os.path.join(repo_root, "data/prerequisites.csv")
    assert os.path.exists(prereq_path), "data/prerequisites.csv must exist"

    result = import_prerequisites(db_session, prereq_path, dry_run=True)
    assert not result["errors"], f"prerequisites had errors: {result['errors']}"
    assert result["inserted"] == 16
    assert result["unchanged"] == 0


# ============================================================================
# 2. Resource Import Validation Rules
# ============================================================================

def test_import_resources_validation_course_must_exist(db_session: Session, tmp_path: Path):
    """Non-existent course title produces validation error."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Non Existent Course",
            "Network Fundamentals",
            "Sample Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Non Existent Course" in e["error"] for e in result["errors"])
    assert result["inserted"] == 0


def test_import_resources_validation_topic_must_exist(db_session: Session, tmp_path: Path):
    """Non-existent topic title produces validation error."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Fake Nonexistent Topic",
            "Sample Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Fake Nonexistent Topic" in e["error"] for e in result["errors"])


def test_import_resources_validation_topic_wrong_course(db_session: Session, tmp_path: Path):
    """Topic belonging to another course produces a membership error."""
    # "ER Model" belongs to "SQL/DBMS", not "Computer Networks"
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "ER Model",
            "Sample Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("does not belong to course" in e["error"] for e in result["errors"])


def test_import_resources_validation_title_cannot_be_empty(db_session: Session, tmp_path: Path):
    """Empty or whitespace-only title produces validation error."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "   ",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any(e["field"] == "title" for e in result["errors"])


def test_import_resources_validation_description_at_least_30_chars(db_session: Session, tmp_path: Path):
    """Description shorter than 30 characters produces validation error."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Valid Title",
            "Too short description",
            "article",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any(e["field"] == "description" for e in result["errors"])


def test_import_resources_validation_allowed_resource_types(db_session: Session, tmp_path: Path):
    """Resource type not in ALLOWED_RESOURCE_TYPES produces validation error."""
    assert ALLOWED_RESOURCE_TYPES == {"article", "video", "tutorial", "documentation"}
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Valid Title",
            "A sufficiently long description with more than thirty chars.",
            "interactive_app",
            "https://example.com/item1",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any(e["field"] == "resource_type" for e in result["errors"])


def test_import_resources_validation_difficulty(db_session: Session, tmp_path: Path):
    """Difficulty must be easy, medium, or hard."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Valid Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/item1",
            "extreme",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any(e["field"] == "difficulty" for e in result["errors"])


def test_import_resources_validation_url_format(db_session: Session, tmp_path: Path):
    """URL must start with http:// or https:// and have a valid host."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Valid Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "ftp://invalid-scheme.com/file",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any(e["field"] == "url" for e in result["errors"])

    # Missing host: "https://"
    csv_file2 = make_csv(
        tmp_path / "res2.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Valid Title",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://",
            "easy",
            "1",
        ]],
    )
    result2 = import_resources(db_session, csv_file2, dry_run=True)
    assert len(result2["errors"]) > 0
    assert any(e["field"] == "url" for e in result2["errors"])


def test_import_resources_duplicate_topic_url_in_file_is_error(db_session: Session, tmp_path: Path):
    """Same (topic, normalized_url) twice in file is an error."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [
            [
                "Computer Networks",
                "Network Fundamentals",
                "First Title",
                "A sufficiently long description with more than thirty chars.",
                "article",
                "https://example.com/page",
                "easy",
                "1",
            ],
            [
                "Computer Networks",
                "Network Fundamentals",
                "Second Title",
                "Another sufficiently long description with more than thirty chars.",
                "tutorial",
                "https://example.com/page/",  # Trailing slash normalizes to same URL
                "medium",
                "2",
            ],
        ],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Duplicate" in e["error"] for e in result["errors"])


def test_import_resources_same_url_different_topics_is_warning(db_session: Session, tmp_path: Path):
    """Same URL used across different topics issues a warning but succeeds."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [
            [
                "Computer Networks",
                "Network Fundamentals",
                "First Topic Res",
                "A sufficiently long description with more than thirty chars.",
                "article",
                "https://example.com/cross-topic",
                "easy",
                "1",
            ],
            [
                "Computer Networks",
                "OSI & TCP/IP Models",
                "Second Topic Res",
                "Another sufficiently long description with more than thirty chars.",
                "article",
                "https://example.com/cross-topic",
                "easy",
                "1",
            ],
        ],
    )
    result = import_resources(db_session, csv_file, dry_run=False)
    assert not result["errors"]
    assert len(result["warnings"]) == 1
    assert "cross-topic" in result["warnings"][0]
    assert result["inserted"] == 2


def test_import_resources_optional_order_defaulting(db_session: Session, tmp_path: Path):
    """Empty order defaults to next free number in that topic."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [
            [
                "Computer Networks",
                "Network Fundamentals",
                "Resource One",
                "A sufficiently long description with more than thirty chars.",
                "article",
                "https://example.com/res1",
                "easy",
                "",  # Empty order -> should become 1
            ],
            [
                "Computer Networks",
                "Network Fundamentals",
                "Resource Two",
                "A sufficiently long description with more than thirty chars.",
                "article",
                "https://example.com/res2",
                "easy",
                "",  # Empty order -> should become 2
            ],
        ],
    )
    result = import_resources(db_session, csv_file, dry_run=False)
    assert not result["errors"]
    assert result["inserted"] == 2

    # Verify orders in DB
    r1 = db_session.query(LearningResource).filter_by(url="https://example.com/res1").first()
    r2 = db_session.query(LearningResource).filter_by(url="https://example.com/res2").first()
    assert r1.order == 1
    assert r2.order == 2


# ============================================================================
# 3. Dry-run, Update vs Insert, Embedding Preservation, Idempotency
# ============================================================================

def test_import_resources_dry_run_writes_nothing(db_session: Session, tmp_path: Path):
    """Dry-run validates rows and calculates counts but persists nothing to DB."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Resource Dry",
            "A sufficiently long description with more than thirty chars.",
            "article",
            "https://example.com/dry-item",
            "easy",
            "1",
        ]],
    )
    result = import_resources(db_session, csv_file, dry_run=True)
    assert not result["errors"]
    assert result["inserted"] == 1

    # Check DB
    count = db_session.query(LearningResource).filter_by(url="https://example.com/dry-item").count()
    assert count == 0


def test_import_resources_update_vs_insert(db_session: Session, tmp_path: Path):
    """Inserts new rows and updates existing rows matching (topic_id, url)."""
    # 1. Insert first item
    csv1 = make_csv(
        tmp_path / "res1.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Original Title",
            "Original description with more than thirty characters.",
            "article",
            "https://example.com/item-to-update",
            "easy",
            "1",
        ]],
    )
    res1 = import_resources(db_session, csv1, dry_run=False)
    assert res1["inserted"] == 1
    assert res1["updated"] == 0

    # 2. Update the existing item and insert a new one
    csv2 = make_csv(
        tmp_path / "res2.csv",
        RESOURCE_HEADER,
        [
            [
                "Computer Networks",
                "Network Fundamentals",
                "Updated Title",
                "Updated description with more than thirty characters now.",
                "video",
                "https://example.com/item-to-update",
                "hard",
                "5",
            ],
            [
                "Computer Networks",
                "Network Fundamentals",
                "Brand New Resource",
                "Brand new description with more than thirty characters.",
                "tutorial",
                "https://example.com/item-new",
                "medium",
                "2",
            ],
        ],
    )
    res2 = import_resources(db_session, csv2, dry_run=False)
    assert res2["inserted"] == 1
    assert res2["updated"] == 1
    assert res2["unchanged"] == 0

    # Verify DB state
    updated_obj = db_session.query(LearningResource).filter_by(url="https://example.com/item-to-update").first()
    assert updated_obj.title == "Updated Title"
    assert updated_obj.resource_type == "video"
    assert updated_obj.difficulty == "hard"
    assert updated_obj.order == 5


def test_import_resources_update_preserves_embedding_and_hash(db_session: Session, tmp_path: Path):
    """Updating resource fields must NEVER overwrite or nullify embedding or embedding_hash."""
    # 1. Insert row
    csv1 = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Initial Title",
            "Initial description with more than thirty characters.",
            "article",
            "https://example.com/item-emb",
            "easy",
            "1",
        ]],
    )
    import_resources(db_session, csv1, dry_run=False)

    # 2. Assign embedding and embedding_hash manually
    resource = db_session.query(LearningResource).filter_by(url="https://example.com/item-emb").first()
    fake_vector = [0.1] * 384
    fake_hash = "abcdef1234567890"
    resource.embedding = fake_vector
    resource.embedding_hash = fake_hash
    db_session.commit()

    # 3. Re-import with updated title and description
    csv2 = make_csv(
        tmp_path / "res_update.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Changed Title",
            "Changed description with more than thirty characters.",
            "article",
            "https://example.com/item-emb",
            "medium",
            "1",
        ]],
    )
    res2 = import_resources(db_session, csv2, dry_run=False)
    assert res2["updated"] == 1

    # 4. Verify embedding and hash are unchanged
    db_session.refresh(resource)
    assert resource.title == "Changed Title"
    assert resource.embedding_hash == fake_hash
    assert len(resource.embedding) == 384
    assert pytest.approx(resource.embedding[0], 0.001) == 0.1


def test_import_resources_idempotent_rerun(db_session: Session, tmp_path: Path):
    """Re-importing identical resource data reports all rows as unchanged."""
    csv_file = make_csv(
        tmp_path / "res.csv",
        RESOURCE_HEADER,
        [[
            "Computer Networks",
            "Network Fundamentals",
            "Stable Title",
            "Stable description with more than thirty characters.",
            "article",
            "https://example.com/stable",
            "medium",
            "1",
        ]],
    )
    res1 = import_resources(db_session, csv_file, dry_run=False)
    assert res1["inserted"] == 1
    assert res1["updated"] == 0

    res2 = import_resources(db_session, csv_file, dry_run=False)
    assert res2["inserted"] == 0
    assert res2["updated"] == 0
    assert res2["unchanged"] == 1


# ============================================================================
# 4. Prerequisite Import Validation Rules
# ============================================================================

def test_import_prerequisites_missing_course(db_session: Session, tmp_path: Path):
    """Missing course title produces validation error."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Unknown Course", "Network Layer", "Data Link Layer"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Unknown Course" in e["error"] for e in result["errors"])


def test_import_prerequisites_missing_topic(db_session: Session, tmp_path: Path):
    """Missing target topic title produces validation error."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "Nonexistent Topic", "Data Link Layer"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Nonexistent Topic" in e["error"] for e in result["errors"])


def test_import_prerequisites_missing_prerequisite_topic(db_session: Session, tmp_path: Path):
    """Missing prerequisite topic title produces validation error."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "Network Layer", "Nonexistent Prereq"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Nonexistent Prereq" in e["error"] for e in result["errors"])


def test_import_prerequisites_topics_different_courses(db_session: Session, tmp_path: Path):
    """Prerequisites across different courses produce validation error."""
    # "Processes & Threads" is in "Operating Systems", "Network Layer" is in "Computer Networks"
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "Network Layer", "Processes & Threads"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("does not belong" in e["error"] for e in result["errors"])


def test_import_prerequisites_self_loop_error(db_session: Session, tmp_path: Path):
    """Self-loop (topic requiring itself) produces validation error."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "Network Layer", "Network Layer"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Self-loop" in e["error"] for e in result["errors"])


def test_import_prerequisites_duplicate_in_file_error(db_session: Session, tmp_path: Path):
    """Duplicate edge in file produces validation error."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [
            ["Computer Networks", "Network Layer", "Data Link Layer"],
            ["Computer Networks", "Network Layer", "Data Link Layer"],
        ],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Duplicate" in e["error"] for e in result["errors"])


# ============================================================================
# 5. Prerequisite Cycle Detection & Operations
# ============================================================================

def test_import_prerequisites_cycle_detection_in_file(db_session: Session, tmp_path: Path):
    """Cycle defined entirely within the file is detected and rejected."""
    # A -> B, B -> C, C -> A
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [
            ["Computer Networks", "OSI & TCP/IP Models", "Network Fundamentals"],
            ["Computer Networks", "Data Link Layer", "OSI & TCP/IP Models"],
            ["Computer Networks", "Network Fundamentals", "Data Link Layer"],  # Closes cycle
        ],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert len(result["errors"]) > 0
    assert any("Cycle detected" in e["error"] for e in result["errors"])
    assert result["inserted"] == 0


def test_import_prerequisites_cycle_detection_with_existing_db_edges(db_session: Session, tmp_path: Path):
    """Cycle formed by combining existing DB edges with imported edges is rejected."""
    # 1. Establish initial chain in DB: B requires A, and C requires B
    csv1 = make_csv(
        tmp_path / "prereq1.csv",
        PREREQ_HEADER,
        [
            ["Computer Networks", "OSI & TCP/IP Models", "Network Fundamentals"],
            ["Computer Networks", "Data Link Layer", "OSI & TCP/IP Models"],
        ],
    )
    res1 = import_prerequisites(db_session, csv1, dry_run=False)
    assert res1["inserted"] == 2

    # 2. Attempt to import edge that completes the cycle: A requires C
    csv2 = make_csv(
        tmp_path / "prereq2.csv",
        PREREQ_HEADER,
        [
            ["Computer Networks", "Network Fundamentals", "Data Link Layer"],
        ],
    )
    res2 = import_prerequisites(db_session, csv2, dry_run=False)
    assert len(res2["errors"]) > 0
    assert any("Cycle detected" in e["error"] for e in res2["errors"])
    assert res2["inserted"] == 0

    # Confirm DB is untouched
    count = db_session.query(TopicPrerequisite).count()
    assert count == 2


def test_import_prerequisites_dry_run_writes_nothing(db_session: Session, tmp_path: Path):
    """Dry-run validates prerequisites and reports counts without writing to DB."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "OSI & TCP/IP Models", "Network Fundamentals"]],
    )
    result = import_prerequisites(db_session, csv_file, dry_run=True)
    assert not result["errors"]
    assert result["inserted"] == 1

    # Check DB
    count = db_session.query(TopicPrerequisite).count()
    assert count == 0


def test_import_prerequisites_idempotent_rerun(db_session: Session, tmp_path: Path):
    """Re-importing identical prerequisite edges reports them as unchanged."""
    csv_file = make_csv(
        tmp_path / "prereq.csv",
        PREREQ_HEADER,
        [["Computer Networks", "OSI & TCP/IP Models", "Network Fundamentals"]],
    )
    res1 = import_prerequisites(db_session, csv_file, dry_run=False)
    assert res1["inserted"] == 1
    assert res1["unchanged"] == 0

    res2 = import_prerequisites(db_session, csv_file, dry_run=False)
    assert res2["inserted"] == 0
    assert res2["unchanged"] == 1

