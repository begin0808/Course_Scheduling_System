"""軟約束:subjects.is_major(S5 主科優先排上午)+ constraint_configs(權重與可調參數)

Revision ID: 0012_soft_constraints
Revises: 0011_schedule_entry_room
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_soft_constraints"
down_revision: str | None = "0011_schedule_entry_room"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column("is_major", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "constraint_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"], ondelete="CASCADE",
            name="fk_constraint_configs_semester_id_semesters",
        ),
        sa.UniqueConstraint("semester_id", "key", name="uq_constraint_configs_semester_key"),
    )
    op.create_index("ix_constraint_configs_semester_id", "constraint_configs", ["semester_id"])


def downgrade() -> None:
    op.drop_table("constraint_configs")
    op.drop_column("subjects", "is_major")
