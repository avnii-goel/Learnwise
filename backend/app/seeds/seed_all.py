"""Idempotent seed script for LearnWise database.

Seeds courses, topics, and question bank questions safely without duplicating rows.
"""

import os
import sys

# Ensure backend root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.question_bank import QUESTIONS
from app.seeds.seed_users import seed_demo_users

COURSES_DATA = [
    {
        "title": "Computer Networks",
        "description": "Foundational and advanced computer networking principles, layers, and protocols.",
    },
    {
        "title": "OOPS",
        "description": "Object-Oriented Programming concepts, principles, and design patterns.",
    },
    {
        "title": "SQL/DBMS",
        "description": "Database management systems, relational modeling, SQL queries, and transactions.",
    },
    {
        "title": "Operating Systems",
        "description": "Operating system architecture, process scheduling, concurrency, and memory management.",
    },
]

TOPICS_DATA = {
    "Computer Networks": [
        "Network Fundamentals",
        "OSI & TCP/IP Models",
        "Data Link Layer",
        "Network Layer",
        "Transport Layer",
        "Application Layer",
    ],
    "OOPS": [
        "OOP Fundamentals",
        "Classes & Objects",
        "Encapsulation & Abstraction",
        "Inheritance",
        "Polymorphism",
        "Exception Handling",
    ],
    "SQL/DBMS": [
        "DBMS Fundamentals",
        "ER Model",
        "Relational Model & SQL",
        "Normalization",
        "Transactions & Concurrency",
        "Indexing",
    ],
    "Operating Systems": [
        "OS Fundamentals",
        "Processes & Threads",
        "CPU Scheduling",
        "Synchronization & Deadlocks",
        "Memory Management",
        "File Systems",
    ],
}


def seed_courses(db: Session) -> tuple[int, int]:
    """Get-or-create courses. Returns (created_count, skipped_count)."""
    created = 0
    skipped = 0

    for course_info in COURSES_DATA:
        existing = (
            db.query(Course)
            .filter(Course.title == course_info["title"])
            .first()
        )
        if existing:
            skipped += 1
        else:
            new_course = Course(
                title=course_info["title"],
                description=course_info["description"]
            )
            db.add(new_course)
            created += 1

    db.commit()
    return created, skipped


def seed_topics(db: Session) -> tuple[int, int]:
    """Get-or-create topics for each course. Never deletes rows. Returns (created_count, skipped_count)."""
    created = 0
    skipped = 0

    for course_title, topic_titles in TOPICS_DATA.items():
        course = (
            db.query(Course)
            .filter(Course.title == course_title)
            .first()
        )
        if not course:
            raise RuntimeError(f"Course '{course_title}' must exist before seeding topics.")

        for index, topic_title in enumerate(topic_titles, start=1):
            existing = (
                db.query(Topic)
                .filter(
                    Topic.course_id == course.id,
                    Topic.title == topic_title
                )
                .first()
            )
            if existing:
                skipped += 1
            else:
                new_topic = Topic(
                    course_id=course.id,
                    title=topic_title,
                    description=f"{topic_title} concepts and fundamentals.",
                    order=index
                )
                db.add(new_topic)
                created += 1

    db.commit()
    return created, skipped


def seed_questions(db: Session) -> tuple[int, int]:
    """Insert questions from question_bank, skipping any where (topic_id, question_text) exists.

    Returns (created_count, skipped_count).
    """
    created = 0
    skipped = 0

    # Map (course_title, topic_title) -> topic_id
    topic_rows = (
        db.query(Topic.id, Topic.title, Course.title)
        .join(Course, Topic.course_id == Course.id)
        .all()
    )
    topic_map = {(course_title, topic_title): topic_id for topic_id, topic_title, course_title in topic_rows}

    # Query all existing (topic_id, question_text) pairs for efficient lookup
    existing_pairs = set(
        db.query(Question.topic_id, Question.question_text).all()
    )

    for q_data in QUESTIONS:
        course_title = q_data["course"]
        topic_title = q_data["topic"]
        topic_id = topic_map.get((course_title, topic_title))

        if not topic_id:
            raise RuntimeError(f"Topic not found for question: {course_title} -> {topic_title}")

        pair = (topic_id, q_data["question_text"])
        if pair in existing_pairs:
            skipped += 1
        else:
            new_question = Question(
                topic_id=topic_id,
                question_text=q_data["question_text"],
                option_a=q_data["option_a"],
                option_b=q_data["option_b"],
                option_c=q_data["option_c"],
                option_d=q_data["option_d"],
                correct_answer=q_data["correct_answer"],
                difficulty=q_data["difficulty"],
            )
            db.add(new_question)
            existing_pairs.add(pair)
            created += 1

    db.commit()
    return created, skipped


def run_seeds():
    """Runs all seed operations and prints created vs skipped counts."""
    db = SessionLocal()
    try:
        print("--- Starting database seeding ---")

        courses_created, courses_skipped = seed_courses(db)
        print(f"Courses   : {courses_created} created, {courses_skipped} skipped")

        topics_created, topics_skipped = seed_topics(db)
        print(f"Topics    : {topics_created} created, {topics_skipped} skipped")

        questions_created, questions_skipped = seed_questions(db)
        print(f"Questions : {questions_created} created, {questions_skipped} skipped")

        users_created, users_skipped = seed_demo_users(db)
        if users_created or users_skipped:
            print(f"Users     : {users_created} created, {users_skipped} skipped")

        print("--- Seeding completed successfully ---")
        return {
            "courses": (courses_created, courses_skipped),
            "topics": (topics_created, topics_skipped),
            "questions": (questions_created, questions_skipped),
            "users": (users_created, users_skipped),
        }
    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seeds()
