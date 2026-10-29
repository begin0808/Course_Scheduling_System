"""v1.4.0:代導(導師請假當天由誰代他帶班)。

新增一張表 `homeroom_covers`,不改既有資料表與資料:從任何 v1.3.x 升上來,
已登記的假單不會補產生代導(使用者定案),只有升級後新登記的假單才會有。

Revision ID: 0019_homeroom_covers
Revises: 0018_alternate_weeks
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_homeroom_covers"
down_revision = "0018_alternate_weeks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "homeroom_covers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leave_request_id", sa.Integer(),
                  sa.ForeignKey("leave_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("semester_id", sa.Integer(),
                  sa.ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.Integer(),
                  sa.ForeignKey("class_units.id", ondelete="SET NULL"), nullable=True),
        sa.Column("class_name", sa.String(length=32), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("from_time", sa.Time(), nullable=True),
        sa.Column("to_time", sa.Time(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("no_cover", sa.Boolean(), nullable=False),
        sa.Column("handler_teacher_id", sa.Integer(),
                  sa.ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_by_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("leave_request_id", "class_name", "date",
                            name="uq_homeroom_covers_day"),
    )
    for col in ("leave_request_id", "semester_id", "class_id", "date", "handler_teacher_id"):
        op.create_index(f"ix_homeroom_covers_{col}", "homeroom_covers", [col])


def downgrade() -> None:
    op.drop_table("homeroom_covers")
