"""add prospect_notes to prospects

Revision ID: b3a91c4d7e25
Revises: 9d775f0fb6fc
Create Date: 2026-08-11 09:14:31.115204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3a91c4d7e25'
down_revision: Union[str, None] = '9d775f0fb6fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, so no server_default is needed against existing rows (contrast
    # 9d775f0fb6fc, whose column is NOT NULL): "no notes yet" and "notes cleared" are
    # the same state here, and NULL says it without inventing a sentinel.
    op.add_column('prospects', sa.Column('prospect_notes', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('prospects', 'prospect_notes')
