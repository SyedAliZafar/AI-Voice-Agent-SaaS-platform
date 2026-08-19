"""add system_prompt_override to calls

Revision ID: a7c41e9b2d38
Revises: f3b8c5d02a17
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c41e9b2d38'
down_revision: Union[str, None] = 'f3b8c5d02a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no server_default: null is the meaningful "no personalization, use
    # Agent.system_prompt" case that every existing row and every plain test call wants,
    # so backfilling anything here would be wrong.
    op.add_column('calls', sa.Column('system_prompt_override', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('calls', 'system_prompt_override')
