"""add prospects

Revision ID: 542867cd778e
Revises: 94e1423d32bc
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '542867cd778e'
down_revision: Union[str, None] = '94e1423d32bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('prospects',
    sa.Column('google_place_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('category', sa.String(length=255), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('review_count', sa.Integer(), nullable=False),
    sa.Column('source_query', sa.String(length=255), nullable=False),
    sa.Column('research_status', sa.String(length=20), nullable=False),
    sa.Column('research', sa.JSON(), nullable=False),
    sa.Column('research_error', sa.Text(), nullable=True),
    sa.Column('outreach_status', sa.String(length=20), nullable=False),
    sa.Column('last_called_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('call_count', sa.Integer(), nullable=False),
    sa.Column('priority_score', sa.Float(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prospects_tenant_id'), 'prospects', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_prospects_google_place_id'), 'prospects', ['google_place_id'], unique=False)
    op.create_index(op.f('ix_prospects_priority_score'), 'prospects', ['priority_score'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_prospects_priority_score'), table_name='prospects')
    op.drop_index(op.f('ix_prospects_google_place_id'), table_name='prospects')
    op.drop_index(op.f('ix_prospects_tenant_id'), table_name='prospects')
    op.drop_table('prospects')
