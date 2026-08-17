"""add leads

Revision ID: a1c9e4f728b6
Revises: d58a3b1c9f47
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e4f728b6'
down_revision: Union[str, None] = 'd58a3b1c9f47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('leads',
    sa.Column('contact_name', sa.String(length=255), nullable=True),
    sa.Column('business_name', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('city', sa.String(length=255), nullable=True),
    sa.Column('country', sa.String(length=255), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('bark_request_id', sa.String(length=255), nullable=True),
    sa.Column('service_requested', sa.String(length=255), nullable=True),
    sa.Column('budget', sa.String(length=100), nullable=True),
    sa.Column('request_text', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('retry_state', sa.String(length=20), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_outcome', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leads_tenant_id'), 'leads', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_leads_retry_state'), 'leads', ['retry_state'], unique=False)
    op.create_index(op.f('ix_leads_status'), 'leads', ['status'], unique=False)

    op.add_column('calls', sa.Column('lead_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_calls_lead_id_leads', 'calls', 'leads', ['lead_id'], ['id'])
    op.create_index(op.f('ix_calls_lead_id'), 'calls', ['lead_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_calls_lead_id'), table_name='calls')
    op.drop_constraint('fk_calls_lead_id_leads', 'calls', type_='foreignkey')
    op.drop_column('calls', 'lead_id')

    op.drop_index(op.f('ix_leads_status'), table_name='leads')
    op.drop_index(op.f('ix_leads_retry_state'), table_name='leads')
    op.drop_index(op.f('ix_leads_tenant_id'), table_name='leads')
    op.drop_table('leads')
