"""add city, country to prospects

Revision ID: c47f2e918a3b
Revises: b3a91c4d7e25
Create Date: 2026-08-11 10:05:44.221037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c47f2e918a3b'
down_revision: Union[str, None] = 'b3a91c4d7e25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both nullable, no server_default: existing rows (sourced before this column
    # existed, or from a CSV import with no city column) genuinely have no known
    # city/country rather than a placeholder value. Backfilling real data for existing
    # rows is a separate step (re-fetch from Google), not something a migration default
    # can do.
    op.add_column('prospects', sa.Column('city', sa.String(length=255), nullable=True))
    op.add_column('prospects', sa.Column('country', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('prospects', 'country')
    op.drop_column('prospects', 'city')
