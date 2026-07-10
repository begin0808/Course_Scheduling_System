"""M4-3:全域系統設定(SMTP)。

Revision ID: 0015_app_settings
Revises: 0014_substitutions
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_app_settings"
down_revision = "0014_substitutions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
