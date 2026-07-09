"""課表版本與格位:timetables / schedule_entries

Revision ID: 0009_timetables
Revises: 0008_assignments
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_timetables"
down_revision: str | None = "0008_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "timetables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"], ondelete="CASCADE",
            name="fk_timetables_semester_id_semesters",
        ),
    )
    op.create_index("ix_timetables_semester_id", "timetables", ["semester_id"])

    op.create_table(
        "schedule_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timetable_id", sa.Integer(), nullable=False),
        sa.Column("course_assignment_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["timetable_id"], ["timetables.id"], ondelete="CASCADE",
            name="fk_schedule_entries_timetable_id_timetables",
        ),
        sa.ForeignKeyConstraint(
            ["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE",
            name="fk_schedule_entries_course_assignment_id_course_assignments",
        ),
    )
    op.create_index("ix_schedule_entries_timetable_id", "schedule_entries", ["timetable_id"])
    op.create_index(
        "ix_schedule_entries_course_assignment_id", "schedule_entries", ["course_assignment_id"]
    )


def downgrade() -> None:
    op.drop_table("schedule_entries")
    op.drop_table("timetables")
