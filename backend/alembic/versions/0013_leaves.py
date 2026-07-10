"""M4-1:請假、受影響節次、通知。

Revision ID: 0013_leaves
Revises: 0012_soft_constraints
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_leaves"
down_revision = "0012_soft_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("leave_type", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="registered"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_leave_requests_semester_id", "leave_requests", ["semester_id"])
    op.create_index("ix_leave_requests_teacher_id", "leave_requests", ["teacher_id"])
    op.create_index("ix_leave_requests_start_date", "leave_requests", ["start_date"])
    op.create_index("ix_leave_requests_end_date", "leave_requests", ["end_date"])

    op.create_table(
        "affected_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leave_request_id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        # 快照欄位:課表改版後仍保留展開當下的事實
        sa.Column("period_name", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("subject_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("class_names", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("room_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("schedule_entry_id", sa.Integer(), nullable=True),
        sa.Column("course_assignment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("handler_teacher_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["leave_request_id"], ["leave_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["schedule_entry_id"], ["schedule_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["course_assignment_id"], ["course_assignments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["handler_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "leave_request_id", "date", "period_no", "class_names",
            name="uq_affected_periods_slot",
        ),
    )
    op.create_index(
        "ix_affected_periods_leave_request_id", "affected_periods", ["leave_request_id"]
    )
    op.create_index("ix_affected_periods_semester_id", "affected_periods", ["semester_id"])
    op.create_index("ix_affected_periods_date", "affected_periods", ["date"])
    op.create_index(
        "ix_affected_periods_course_assignment_id", "affected_periods", ["course_assignment_id"]
    )
    op.create_index(
        "ix_affected_periods_handler_teacher_id", "affected_periods", ["handler_teacher_id"]
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_notifications_semester_id", "notifications", ["semester_id"])
    op.create_index("ix_notifications_teacher_id", "notifications", ["teacher_id"])
    op.create_index("ix_notifications_type", "notifications", ["type"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("affected_periods")
    op.drop_table("leave_requests")
