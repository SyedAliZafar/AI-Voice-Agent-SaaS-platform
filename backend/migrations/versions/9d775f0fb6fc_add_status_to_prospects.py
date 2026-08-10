"""add status to prospects

Revision ID: 9d775f0fb6fc
Revises: 79342e6251f7
Create Date: 2026-08-10 04:52:02.042853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d775f0fb6fc'
down_revision: Union[str, None] = '79342e6251f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default added by hand (same reasoning as
    # 79342e6251f7_add_llm_model_to_agents.py): "prospects" already has rows, so a NOT
    # NULL column with no default fails against them. Existing rows land on
    # 'not_called' — deliberately not back-filled from outreach_status, which is a
    # separate axis this column does not replace (see backend/models/prospect.py).
    op.add_column(
        'prospects',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='not_called'),
    )
    op.create_index(op.f('ix_prospects_status'), 'prospects', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_prospects_status'), table_name='prospects')
    op.drop_column('prospects', 'status')
