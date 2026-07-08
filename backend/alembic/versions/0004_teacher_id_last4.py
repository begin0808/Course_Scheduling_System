"""teachers 增加 id_last4 欄位

Revision ID: 0004_teacher_id_last4
Revises: 0003_basedata
Create Date: 2026-07-08
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_teacher_id_last4"
down_revision: str | None = "0003_basedata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("teachers", sa.Column("id_last4", sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column("teachers", "id_last4")
