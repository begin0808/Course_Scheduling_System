"""教師、科目、場地、班級、教師時段規則

Revision ID: 0003_basedata
Revises: 0002_semester_period
Create Date: 2026-07-08
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_basedata"
down_revision: str | None = "0002_semester_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sem_fk(col: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], ["semesters.id"], name=f"fk_{table}_{col}_semesters", ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=True),
        sa.Column("required_room_type", sa.String(length=20), nullable=True),
        sa.Column("default_block_size", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name="pk_subjects"),
        _sem_fk("semester_id", "subjects"),
    )
    op.create_index("ix_subjects_semester_id", "subjects", ["semester_id"])

    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("base_periods", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_title", sa.String(length=32), nullable=True),
        sa.Column("admin_reduction", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id", name="pk_teachers"),
        _sem_fk("semester_id", "teachers"),
    )
    op.create_index("ix_teachers_semester_id", "teachers", ["semester_id"])

    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("room_type", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
        _sem_fk("semester_id", "rooms"),
    )
    op.create_index("ix_rooms_semester_id", "rooms", ["semester_id"])

    op.create_table(
        "class_units",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("track", sa.String(length=20), nullable=False),
        sa.Column("department", sa.String(length=32), nullable=True),
        sa.Column("student_count", sa.Integer(), nullable=True),
        sa.Column("homeroom_teacher_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_class_units"),
        _sem_fk("semester_id", "class_units"),
        sa.ForeignKeyConstraint(
            ["homeroom_teacher_id"], ["teachers.id"],
            name="fk_class_units_homeroom_teacher_id_teachers", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_class_units_semester_id", "class_units", ["semester_id"])
    op.create_index("ix_class_units_homeroom_teacher_id", "class_units", ["homeroom_teacher_id"])

    op.create_table(
        "teacher_time_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_teacher_time_rules"),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"],
            name="fk_teacher_time_rules_teacher_id_teachers", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "teacher_id", "weekday", "period_no", name="uq_teacher_time_rules_cell"
        ),
    )
    op.create_index("ix_teacher_time_rules_teacher_id", "teacher_time_rules", ["teacher_id"])

    op.create_table(
        "teacher_subjects",
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("teacher_id", "subject_id", name="pk_teacher_subjects"),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"],
            name="fk_teacher_subjects_teacher_id_teachers", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"],
            name="fk_teacher_subjects_subject_id_subjects", ondelete="CASCADE",
        ),
    )

    op.create_table(
        "room_subjects",
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("room_id", "subject_id", name="pk_room_subjects"),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"],
            name="fk_room_subjects_room_id_rooms", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"],
            name="fk_room_subjects_subject_id_subjects", ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("room_subjects")
    op.drop_table("teacher_subjects")
    op.drop_index("ix_teacher_time_rules_teacher_id", table_name="teacher_time_rules")
    op.drop_table("teacher_time_rules")
    op.drop_index("ix_class_units_homeroom_teacher_id", table_name="class_units")
    op.drop_index("ix_class_units_semester_id", table_name="class_units")
    op.drop_table("class_units")
    op.drop_index("ix_rooms_semester_id", table_name="rooms")
    op.drop_table("rooms")
    op.drop_index("ix_teachers_semester_id", table_name="teachers")
    op.drop_table("teachers")
    op.drop_index("ix_subjects_semester_id", table_name="subjects")
    op.drop_table("subjects")
