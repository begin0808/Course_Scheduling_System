"""wizard_state 單例資料表

Revision ID: 0005_wizard_state
Revises: 0004_teacher_id_last4
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_wizard_state"
down_revision: str | None = "0004_teacher_id_last4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wizard_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semester_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_wizard_state"),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"],
            name="fk_wizard_state_semester_id_semesters", ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("wizard_state")
