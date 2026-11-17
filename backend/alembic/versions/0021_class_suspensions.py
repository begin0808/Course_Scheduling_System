"""v1.4.19:停課日(全校、年級或指定班級,整天或第幾節到第幾節不上課)。

新增兩張表,不改既有資料表與資料。升級前已登記的請假節次不會因此改變;
之後新設的停課,設定時會列出時段裡已經安排的調代課,由組長自行處理。

Revision ID: 0021_class_suspensions
Revises: 0020_relink_swaps
"""

import sqlalchemy as sa

from alembic import op

revision = "0021_class_suspensions"
down_revision = "0020_relink_swaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "class_suspensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(),
                  sa.ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("whole_school", sa.Boolean(), nullable=False),
        sa.Column("from_ordinal", sa.Integer(), nullable=True),
        sa.Column("to_ordinal", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_by_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    for col in ("semester_id", "start_date", "end_date"):
        op.create_index(f"ix_class_suspensions_{col}", "class_suspensions", [col])
    op.create_table(
        "class_suspension_classes",
        sa.Column("suspension_id", sa.Integer(),
                  sa.ForeignKey("class_suspensions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("class_unit_id", sa.Integer(),
                  sa.ForeignKey("class_units.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_class_suspension_classes_class_unit_id",
                    "class_suspension_classes", ["class_unit_id"])


def downgrade() -> None:
    op.drop_table("class_suspension_classes")
    op.drop_table("class_suspensions")
