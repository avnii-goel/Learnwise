"""add_adaptive_quizzing_tables_and_columns

Revision ID: c2a5d91e4b8f
Revises: 7e4c32b013e9
Create Date: 2026-10-31 01:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2a5d91e4b8f'
down_revision: Union[str, Sequence[str], None] = '7e4c32b013e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Alter quiz_attempts: add mode, status, topic_id
    op.add_column(
        'quiz_attempts',
        sa.Column('mode', sa.String(length=16), server_default='fixed', nullable=False)
    )
    op.create_check_constraint(
        'chk_quiz_attempts_mode',
        'quiz_attempts',
        "mode IN ('fixed', 'adaptive')"
    )

    op.add_column(
        'quiz_attempts',
        sa.Column('status', sa.String(length=16), server_default='completed', nullable=False)
    )
    op.create_check_constraint(
        'chk_quiz_attempts_status',
        'quiz_attempts',
        "status IN ('in_progress', 'completed')"
    )

    op.add_column(
        'quiz_attempts',
        sa.Column('topic_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_quiz_attempts_topic_id',
        'quiz_attempts',
        'topics',
        ['topic_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Partial unique index: only ONE in_progress adaptive attempt per (user_id, topic_id)
    op.create_index(
        'uq_adaptive_quiz_in_progress',
        'quiz_attempts',
        ['user_id', 'topic_id'],
        unique=True,
        postgresql_where=sa.text("mode = 'adaptive' AND status = 'in_progress'")
    )

    # 2. Create adaptive_quiz_steps table
    op.create_table(
        'adaptive_quiz_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('target_difficulty', sa.String(length=16), nullable=False),
        sa.Column('served_difficulty', sa.String(length=16), nullable=False),
        sa.Column('selection_reason', sa.String(length=32), nullable=False),
        sa.Column('mastery_before', sa.Float(), nullable=False),
        sa.Column('mastery_after', sa.Float(), nullable=True),
        sa.Column('selected_answer', sa.String(length=1), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('served_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['attempt_id'], ['quiz_attempts.id'], name='fk_adaptive_steps_attempt_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], name='fk_adaptive_steps_question_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_id', 'step_number', name='uq_adaptive_steps_attempt_step'),
        sa.UniqueConstraint('attempt_id', 'question_id', name='uq_adaptive_steps_attempt_question'),
    )
    op.create_index(
        'ix_adaptive_quiz_steps_attempt_id',
        'adaptive_quiz_steps',
        ['attempt_id'],
        unique=False
    )
    op.create_index(
        op.f('ix_adaptive_quiz_steps_id'),
        'adaptive_quiz_steps',
        ['id'],
        unique=False
    )

    # 3. Enable Row Level Security (RLS) with no policies
    op.execute("ALTER TABLE adaptive_quiz_steps ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop adaptive_quiz_steps
    op.drop_index(op.f('ix_adaptive_quiz_steps_id'), table_name='adaptive_quiz_steps')
    op.drop_index('ix_adaptive_quiz_steps_attempt_id', table_name='adaptive_quiz_steps')
    op.drop_table('adaptive_quiz_steps')

    # 2. Drop partial unique index
    op.drop_index('uq_adaptive_quiz_in_progress', table_name='quiz_attempts')

    # 3. Drop quiz_attempts foreign key, constraints, and columns
    op.drop_constraint('fk_quiz_attempts_topic_id', 'quiz_attempts', type_='foreignkey')
    op.drop_column('quiz_attempts', 'topic_id')
    op.drop_constraint('chk_quiz_attempts_status', 'quiz_attempts', type_='check')
    op.drop_column('quiz_attempts', 'status')
    op.drop_constraint('chk_quiz_attempts_mode', 'quiz_attempts', type_='check')
    op.drop_column('quiz_attempts', 'mode')

