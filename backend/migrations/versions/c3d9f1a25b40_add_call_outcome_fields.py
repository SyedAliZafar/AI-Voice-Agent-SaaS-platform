"""add prospect_id, disconnection_reason, answered_by_human to calls

Revision ID: c3d9f1a25b40
Revises: b8d2e6a41f39
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9f1a25b40'
down_revision: Union[str, None] = 'b8d2e6a41f39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All three nullable with no server_default: every existing row predates prospect
    # outreach through the app, so null is the correct "not applicable / not known yet"
    # value for each. Backfilling would invent outcomes we never observed.
    op.add_column('calls', sa.Column('prospect_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_calls_prospect_id_prospects', 'calls', 'prospects', ['prospect_id'], ['id']
    )
    op.create_index(op.f('ix_calls_prospect_id'), 'calls', ['prospect_id'], unique=False)
    op.add_column('calls', sa.Column('disconnection_reason', sa.String(length=64), nullable=True))
    op.add_column('calls', sa.Column('answered_by_human', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('calls', 'answered_by_human')
    op.drop_column('calls', 'disconnection_reason')
    op.drop_index(op.f('ix_calls_prospect_id'), table_name='calls')
    op.drop_constraint('fk_calls_prospect_id_prospects', 'calls', type_='foreignkey')
    op.drop_column('calls', 'prospect_id')
