"""add_recommender_tables_and_columns

Revision ID: 7e4c32b013e9
Revises: a7a34be56dbb
Create Date: 2026-10-30 11:12:35.731377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '7e4c32b013e9'
down_revision: Union[str, Sequence[str], None] = 'a7a34be56dbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Modify learning_resources table
    op.add_column(
        'learning_resources',
        sa.Column('difficulty', sa.String(length=20), server_default='medium', nullable=False)
    )
    op.add_column(
        'learning_resources',
        sa.Column('embedding', Vector(384), nullable=True)
    )
    op.add_column(
        'learning_resources',
        sa.Column('embedding_hash', sa.Text(), nullable=True)
    )
    op.create_unique_constraint(
        'uq_learning_resources_topic_url',
        'learning_resources',
        ['topic_id', 'url']
    )

    # 3. Create topic_prerequisites table
    op.create_table(
        'topic_prerequisites',
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('prerequisite_topic_id', sa.Integer(), nullable=False),
        sa.CheckConstraint('topic_id <> prerequisite_topic_id', name='chk_topic_prerequisites_no_self'),
        sa.ForeignKeyConstraint(['prerequisite_topic_id'], ['topics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('topic_id', 'prerequisite_topic_id', name='pk_topic_prerequisites')
    )
    op.execute("ALTER TABLE topic_prerequisites ENABLE ROW LEVEL SECURITY")

    # 4. Create recommendation_impressions table
    op.create_table(
        'recommendation_impressions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('strategy', sa.String(length=32), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('mastery_at_shown', sa.Float(), nullable=True),
        sa.Column('components', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('shown_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('clicked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.ForeignKeyConstraint(['resource_id'], ['learning_resources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recommendation_impressions_id'), 'recommendation_impressions', ['id'], unique=False)
    op.create_index('ix_recommendation_impressions_user_shown', 'recommendation_impressions', ['user_id', 'shown_at'], unique=False)
    op.create_index('ix_recommendation_impressions_resource', 'recommendation_impressions', ['resource_id'], unique=False)
    op.execute("ALTER TABLE recommendation_impressions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE recommendation_impressions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE topic_prerequisites DISABLE ROW LEVEL SECURITY")

    op.drop_index('ix_recommendation_impressions_resource', table_name='recommendation_impressions')
    op.drop_index('ix_recommendation_impressions_user_shown', table_name='recommendation_impressions')
    op.drop_index(op.f('ix_recommendation_impressions_id'), table_name='recommendation_impressions')
    op.drop_table('recommendation_impressions')

    op.drop_table('topic_prerequisites')

    op.drop_constraint('uq_learning_resources_topic_url', 'learning_resources', type_='unique')
    op.drop_column('learning_resources', 'embedding_hash')
    op.drop_column('learning_resources', 'embedding')
    op.drop_column('learning_resources', 'difficulty')

    op.execute("DROP EXTENSION IF EXISTS vector")
