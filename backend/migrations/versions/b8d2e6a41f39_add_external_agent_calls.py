"""allow calls placed through a platform-native agent

Makes calls.agent_id nullable and adds calls.external_agent_id, so a call dialed
through an agent that lives in the voice platform's own dashboard (ADR-012) can be
recorded without inventing a local Agent row for it.

Revision ID: b8d2e6a41f39
Revises: a7c41e9b2d38
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d2e6a41f39'
down_revision: Union[str, None] = 'a7c41e9b2d38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widening a NOT NULL to nullable is safe on existing rows — every current call was
    # placed by a local agent and keeps its agent_id.
    op.alter_column('calls', 'agent_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column('calls', sa.Column('external_agent_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_calls_external_agent_id'), 'calls', ['external_agent_id'], unique=False)


def downgrade() -> None:
    # Rows with no agent_id can't be represented once the column is NOT NULL again, and
    # a guessed backfill would silently attribute someone else's calls to a local agent.
    # Drop them — they only exist if the external-dial path was used.
    op.execute('DELETE FROM calls WHERE agent_id IS NULL')
    op.drop_index(op.f('ix_calls_external_agent_id'), table_name='calls')
    op.drop_column('calls', 'external_agent_id')
    op.alter_column('calls', 'agent_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
