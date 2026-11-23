"""add student nationality

Revision ID: 7c3e1a9d4b52
Revises: 2ebecc0f9713
Create Date: 2026-11-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c3e1a9d4b52'
down_revision = '2ebecc0f9713'
branch_labels = None
depends_on = None


def upgrade():
    # server_default fills existing rows, so NOT NULL is safe on a populated table.
    with op.batch_alter_table('student', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nationality', sa.String(length=100), nullable=False, server_default=''))


def downgrade():
    with op.batch_alter_table('student', schema=None) as batch_op:
        batch_op.drop_column('nationality')
