"""配課領域:scheduling_units / members / course_assignments / assignment_teachers / block_rules

Revision ID: 0008_assignments
Revises: 0007_teacher_account_contact
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_assignments"
down_revision: str | None = "0007_teacher_account_contact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduling_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("unit_type", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"], ondelete="CASCADE",
            name="fk_scheduling_units_semester_id_semesters",
        ),
    )
    op.create_index("ix_scheduling_units_semester_id", "scheduling_units", ["semester_id"])

    op.create_table(
        "scheduling_unit_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheduling_unit_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scheduling_unit_id"], ["scheduling_units.id"], ondelete="CASCADE",
            name="fk_scheduling_unit_members_scheduling_unit_id_scheduling_units",
        ),
        sa.ForeignKeyConstraint(
            ["class_unit_id"], ["class_units.id"], ondelete="CASCADE",
            name="fk_scheduling_unit_members_class_unit_id_class_units",
        ),
        sa.UniqueConstraint(
            "scheduling_unit_id", "class_unit_id", name="uq_scheduling_unit_members_pair"
        ),
    )
    op.create_index(
        "ix_scheduling_unit_members_scheduling_unit_id",
        "scheduling_unit_members", ["scheduling_unit_id"],
    )
    op.create_index(
        "ix_scheduling_unit_members_class_unit_id",
        "scheduling_unit_members", ["class_unit_id"],
    )

    op.create_table(
        "course_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("scheduling_unit_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("periods_per_week", sa.Integer(), nullable=False),
        sa.Column("required_room_type", sa.String(length=20), nullable=True),
        sa.Column("room_id", sa.Integer(), nullable=True),
        sa.Column("lock_room", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"], ondelete="CASCADE",
            name="fk_course_assignments_semester_id_semesters",
        ),
        sa.ForeignKeyConstraint(
            ["scheduling_unit_id"], ["scheduling_units.id"], ondelete="CASCADE",
            name="fk_course_assignments_scheduling_unit_id_scheduling_units",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], ondelete="CASCADE",
            name="fk_course_assignments_subject_id_subjects",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="SET NULL",
            name="fk_course_assignments_room_id_rooms",
        ),
    )
    op.create_index("ix_course_assignments_semester_id", "course_assignments", ["semester_id"])
    op.create_index(
        "ix_course_assignments_scheduling_unit_id", "course_assignments", ["scheduling_unit_id"]
    )
    op.create_index("ix_course_assignments_subject_id", "course_assignments", ["subject_id"])
    op.create_index("ix_course_assignments_room_id", "course_assignments", ["room_id"])

    op.create_table(
        "assignment_teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_assignment_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("is_lead", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(
            ["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE",
            name="fk_assignment_teachers_course_assignment_id_course_assignments",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"], ondelete="CASCADE",
            name="fk_assignment_teachers_teacher_id_teachers",
        ),
        sa.UniqueConstraint(
            "course_assignment_id", "teacher_id", name="uq_assignment_teachers_pair"
        ),
    )
    op.create_index(
        "ix_assignment_teachers_course_assignment_id",
        "assignment_teachers", ["course_assignment_id"],
    )
    op.create_index("ix_assignment_teachers_teacher_id", "assignment_teachers", ["teacher_id"])

    op.create_table(
        "block_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_assignment_id", sa.Integer(), nullable=False),
        sa.Column("block_size", sa.Integer(), nullable=False),
        sa.Column("count_per_week", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE",
            name="fk_block_rules_course_assignment_id_course_assignments",
        ),
    )
    op.create_index(
        "ix_block_rules_course_assignment_id", "block_rules", ["course_assignment_id"]
    )


def downgrade() -> None:
    op.drop_table("block_rules")
    op.drop_table("assignment_teachers")
    op.drop_table("course_assignments")
    op.drop_table("scheduling_unit_members")
    op.drop_table("scheduling_units")
