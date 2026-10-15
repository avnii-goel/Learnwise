"""Enable row level security on application tables

Revision ID: d912201f9dc6
Revises: df94f9873db2
Create Date: 2026-10-16 01:18:54.011027

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd912201f9dc6'
down_revision: Union[str, Sequence[str], None] = 'df94f9873db2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "users",
    "courses",
    "topics",
    "learning_resources",
    "questions",
    "quiz_attempts",
    "quiz_responses",
]


def upgrade() -> None:
    """Enable Row Level Security on all application tables."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Disable Row Level Security on all application tables."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
