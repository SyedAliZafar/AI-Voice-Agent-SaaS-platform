"""add source_location to prospects

Revision ID: d58a3b1c9f47
Revises: c47f2e918a3b
Create Date: 2026-08-11 11:22:09.664201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd58a3b1c9f47'
down_revision: Union[str, None] = 'c47f2e918a3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no server_default: existing rows genuinely do not know which location
    # their discovery run was scoped to — that input was discarded before this column
    # existed, and there is nothing to back-fill it from (the address is the *result*
    # of the search, not the search term). Same reasoning as c47f2e918a3b.
    op.add_column('prospects', sa.Column('source_location', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('prospects', 'source_location')
