"""add requests table + request_id FK on approvals

Revision ID: d9a1c2e3f4b5
Revises: 78bc7232c288
Create Date: 2026-07-25 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd9a1c2e3f4b5'
down_revision: Union[str, None] = '78bc7232c288'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- requests table ---
    op.create_table(
        'requests',
        sa.Column(
            'type',
            sa.Enum(
                'reservation', 'modification', 'cancellation', 'order',
                'enquiry', 'complaint', 'callback', 'other',
                name='request_type', native_enum=False, length=32,
            ),
            server_default='enquiry',
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum(
                'new', 'needs_review', 'approved', 'rejected',
                'in_progress', 'completed', 'failed', 'cancelled',
                name='request_status', native_enum=False, length=32,
            ),
            server_default='new',
            nullable=False,
        ),
        sa.Column(
            'priority',
            sa.Enum(
                'normal', 'high',
                name='request_priority', native_enum=False, length=32,
            ),
            server_default='normal',
            nullable=False,
        ),
        sa.Column('summary', sa.String(length=255), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('resolution', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('guest_id', sa.UUID(), nullable=True),
        sa.Column('channel_type',
                  sa.Enum('webchat', 'whatsapp', 'sms', 'voice', 'instagram', 'email',
                          name='channel_type', native_enum=False, length=32),
                  nullable=True),
        sa.Column('assigned_to', sa.UUID(), nullable=True),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['guest_id'], ['guests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_requests_tenant_status', 'requests', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_requests_conversation', 'requests', ['conversation_id'], unique=False)

    # --- request_id FK on approvals ---
    op.add_column('approvals',
        sa.Column('request_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_approvals_request_id_requests', 'approvals', 'requests',
        ['request_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_approvals_request_id_requests', 'approvals', type_='foreignkey')
    op.drop_column('approvals', 'request_id')
    op.drop_index('ix_requests_conversation', table_name='requests')
    op.drop_index('ix_requests_tenant_status', table_name='requests')
    op.drop_table('requests')