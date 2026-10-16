import os
import sys
import pytest
from dotenv import load_dotenv

# Ensure backend root is on sys.path
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

# Load environment variables
load_dotenv(os.path.join(backend_root, ".env"))

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- STRICT SAFETY CHECKS ---
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Tests must run against a dedicated local test database, "
        "never the shared production/staging database. Set TEST_DATABASE_URL in backend/.env."
    )

if DATABASE_URL and (TEST_DATABASE_URL.strip() == DATABASE_URL.strip()):
    raise RuntimeError(
        "CRITICAL SAFETY VIOLATION: TEST_DATABASE_URL is identical to DATABASE_URL! "
        "Tests refuse to run to prevent accidental modification of the shared database."
    )

if "supabase.com" in TEST_DATABASE_URL:
    raise RuntimeError(
        "CRITICAL SAFETY VIOLATION: TEST_DATABASE_URL points to Supabase! "
        "Tests must run on a local PostgreSQL instance (e.g., localhost:5433)."
    )

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.course import Course
from app.models.topic import Topic
from app.models.question import Question
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.utils.jwt import create_access_token
from app.utils.security import hash_password
from app.seeds.seed_all import seed_courses, seed_topics, seed_questions

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def apply_migrations_and_seed_data():
    """Applies all Alembic migrations and seeds courses/topics/questions into the test database."""
    alembic_ini_path = os.path.join(backend_root, "alembic.ini")
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    alembic_cfg.set_main_option("script_location", os.path.join(backend_root, "alembic"))

    # Run migrations up to head
    command.upgrade(alembic_cfg, "head")

    # Seed baseline courses, topics, and questions
    with TestSessionLocal() as db:
        seed_courses(db)
        seed_topics(db)
        seed_questions(db)

    yield


@pytest.fixture
def db_session():
    """Provides a transactional database session for each test, cleaning up test rows afterwards."""
    session = TestSessionLocal()
    baseline_courses = ["Computer Networks", "OOPS", "SQL/DBMS", "Operating Systems"]

    def cleanup():
        session.rollback()
        session.query(QuizResponse).delete()
        session.query(QuizAttempt).delete()
        session.query(User).delete()
        non_baseline = session.query(Course).filter(~Course.title.in_(baseline_courses)).all()
        for c in non_baseline:
            session.delete(c)
        session.commit()

    cleanup()
    try:
        yield session
    finally:
        cleanup()
        session.close()


@pytest.fixture
def client(db_session):
    """Provides a TestClient with get_db overridden to use the test database session."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_learner(db_session):
    """Creates and returns a test learner user."""
    user = User(
        name="Test Learner",
        email="test.learner@learnwise.com",
        password_hash=hash_password("LearnerPass123!"),
        role="learner",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_instructor(db_session):
    """Creates and returns a test instructor user."""
    user = User(
        name="Test Instructor",
        email="test.instructor@learnwise.com",
        password_hash=hash_password("InstructorPass123!"),
        role="instructor",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def learner_token(test_learner):
    """Generates a valid JWT access token for the test learner."""
    return create_access_token(test_learner.id)


@pytest.fixture
def instructor_token(test_instructor):
    """Generates a valid JWT access token for the test instructor."""
    return create_access_token(test_instructor.id)
