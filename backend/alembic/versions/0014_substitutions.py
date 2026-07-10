"""M4-2:調代課處置。

Revision ID: 0014_substitutions
Revises: 0013_leaves
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_substitutions"
down_revision = "0013_leaves"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "substitutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("affected_period_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("handler_teacher_id", sa.Integer(), nullable=True),
        sa.Column("counts_toward_hours", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("funding_source", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("swap_date", sa.Date(), nullable=True),
        sa.Column("swap_period_no", sa.Integer(), nullable=True),
        sa.Column("swap_period_name", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("swap_class_names", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("swap_subject_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("swap_entry_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["affected_period_id"], ["affected_periods.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["handler_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["swap_entry_id"], ["schedule_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("affected_period_id", name="uq_substitutions_affected_period"),
    )
    op.create_index("ix_substitutions_semester_id", "substitutions", ["semester_id"])
    op.create_index(
        "ix_substitutions_affected_period_id", "substitutions", ["affected_period_id"]
    )
    op.create_index(
        "ix_substitutions_handler_teacher_id", "substitutions", ["handler_teacher_id"]
    )


def downgrade() -> None:
    op.drop_table("substitutions")
