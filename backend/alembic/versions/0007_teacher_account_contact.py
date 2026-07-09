"""teachers 增加帳號綁定(user_id)與聯絡資訊(email/phone/line_id)

Revision ID: 0007_teacher_account_contact
Revises: 0006_class_period_table
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_teacher_account_contact"
down_revision: str | None = "0006_class_period_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("teachers", sa.Column("email", sa.String(length=128), nullable=True))
    op.add_column("teachers", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("teachers", sa.Column("line_id", sa.String(length=64), nullable=True))
    op.add_column("teachers", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_teachers_user_id_users",
        "teachers", "users",
        ["user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_teachers_user_id", "teachers", ["user_id"])
    op.create_unique_constraint(
        "uq_teachers_semester_user", "teachers", ["semester_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_teachers_semester_user", "teachers", type_="unique")
    op.drop_index("ix_teachers_user_id", table_name="teachers")
    op.drop_constraint("fk_teachers_user_id_users", "teachers", type_="foreignkey")
    op.drop_column("teachers", "user_id")
    op.drop_column("teachers", "line_id")
    op.drop_column("teachers", "phone")
    op.drop_column("teachers", "email")
