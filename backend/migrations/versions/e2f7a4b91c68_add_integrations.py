"""add integrations

Per-tenant third-party connection settings — see backend/models/integration.py for why
this is a new table rather than more tool_configs rows (phase5 Session 1).

Revision ID: e2f7a4b91c68
Revises: a1c9e4f728b6
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f7a4b91c68'
down_revision: Union[str, None] = 'a1c9e4f728b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('integrations',
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_verify_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    # One CRM per tenant — swapping providers overwrites the row rather than leaving a
    # second, dead one behind for the sync to pick up ambiguously.
    sa.UniqueConstraint('tenant_id', 'kind', name='uq_integrations_tenant_kind')
    )
    op.create_index(op.f('ix_integrations_tenant_id'), 'integrations', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_integrations_tenant_id'), table_name='integrations')
    op.drop_table('integrations')
