"""add nda dispatches and tenant NDA party data

One NDA per lead call, with the uniqueness guarantee enforced in the DB rather than in a
per-connection Python set — see backend/models/nda.py (phase5 Session 3).

Revision ID: f3b8c5d02a17
Revises: e2f7a4b91c68
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b8c5d02a17'
down_revision: Union[str, None] = 'e2f7a4b91c68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('nda_dispatches',
    sa.Column('lead_id', sa.UUID(), nullable=False),
    sa.Column('call_id', sa.UUID(), nullable=False),
    sa.Column('recipient_email', sa.String(length=255), nullable=True),
    sa.Column('recipient_name', sa.String(length=255), nullable=True),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('extraction_confidence', sa.Float(), nullable=True),
    sa.Column('extraction_quote', sa.Text(), nullable=True),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('provider_request_id', sa.String(length=255), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('signed_document_url', sa.Text(), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
    sa.ForeignKeyConstraint(['call_id'], ['calls.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    # The reason this table exists rather than columns on leads: an at-least-once Celery
    # delivery must not become an at-least-once legal document.
    sa.UniqueConstraint('lead_id', 'call_id', name='uq_nda_dispatches_lead_call')
    )
    op.create_index(op.f('ix_nda_dispatches_tenant_id'), 'nda_dispatches', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_nda_dispatches_lead_id'), 'nda_dispatches', ['lead_id'], unique=False)
    op.create_index(op.f('ix_nda_dispatches_state'), 'nda_dispatches', ['state'], unique=False)
    op.create_index(op.f('ix_nda_dispatches_provider_request_id'), 'nda_dispatches', ['provider_request_id'], unique=False)

    # NDA merge fields for the platform-owned template, plus the auto-send switch.
    # server_default on nda_auto_send so existing tenant rows get an explicit false
    # rather than a null the model would read as "unset" — the safe default has to be
    # true of rows that predate the column, not just of new ones.
    op.add_column('tenants', sa.Column('nda_company_legal_name', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('nda_signer_name', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('nda_signer_title', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('nda_signer_email', sa.String(length=255), nullable=True))
    op.add_column('tenants', sa.Column('nda_auto_send', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('tenants', 'nda_auto_send')
    op.drop_column('tenants', 'nda_signer_email')
    op.drop_column('tenants', 'nda_signer_title')
    op.drop_column('tenants', 'nda_signer_name')
    op.drop_column('tenants', 'nda_company_legal_name')

    op.drop_index(op.f('ix_nda_dispatches_provider_request_id'), table_name='nda_dispatches')
    op.drop_index(op.f('ix_nda_dispatches_state'), table_name='nda_dispatches')
    op.drop_index(op.f('ix_nda_dispatches_lead_id'), table_name='nda_dispatches')
    op.drop_index(op.f('ix_nda_dispatches_tenant_id'), table_name='nda_dispatches')
    op.drop_table('nda_dispatches')
