"""add call external_id

Revision ID: 4f42c8f91820
Revises: 542867cd778e
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f42c8f91820'
down_revision: Union[str, None] = '542867cd778e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calls', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_calls_external_id'), 'calls', ['external_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_calls_external_id'), table_name='calls')
    op.drop_column('calls', 'external_id')
