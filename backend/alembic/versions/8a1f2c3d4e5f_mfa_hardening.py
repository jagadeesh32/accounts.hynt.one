"""MFA hardening: encrypted secrets, replay guard, recovery codes.

Revision ID: 8a1f2c3d4e5f
Revises: 47dc448f415c
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '8a1f2c3d4e5f'
down_revision = '47dc448f415c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ciphertext is longer than the 64-char base32 it replaces. Any secret
    # already sitting here is plaintext from a setup nobody finished (no user
    # had mfa_enabled when this shipped), so it is dropped rather than
    # re-encrypted — the next "Set up two-factor" mints a fresh one.
    op.alter_column('users', 'mfa_secret', type_=sa.Text(), existing_type=sa.String(64))
    op.execute("UPDATE users SET mfa_secret = NULL WHERE mfa_enabled = false")
    op.add_column('users', sa.Column('mfa_last_used_step', sa.Integer(), nullable=True))

    op.create_table(
        'mfa_recovery_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code_hash'),
    )
    op.create_index('ix_mfa_recovery_codes_user_id', 'mfa_recovery_codes', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_mfa_recovery_codes_user_id', table_name='mfa_recovery_codes')
    op.drop_table('mfa_recovery_codes')
    op.drop_column('users', 'mfa_last_used_step')
    op.execute("UPDATE users SET mfa_secret = NULL")
    op.alter_column('users', 'mfa_secret', type_=sa.String(64), existing_type=sa.Text())
