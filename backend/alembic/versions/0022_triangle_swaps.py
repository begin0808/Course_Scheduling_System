"""v1.4.20:三角調課(同一班三位老師輪流換課)。

`substitutions` 加上第三位老師與中間那一節(乙原本的課,改由丙上),全部可為空;
既有的調課都是兩人互調,這些欄位留空,資料不變。

Revision ID: 0022_triangle_swaps
Revises: 0021_class_suspensions
"""

import sqlalchemy as sa

from alembic import op

revision = "0022_triangle_swaps"
down_revision = "0021_class_suspensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("substitutions") as t:
        t.add_column(sa.Column("tri_teacher_id", sa.Integer(), nullable=True))
        t.add_column(sa.Column("tri_date", sa.Date(), nullable=True))
        t.add_column(sa.Column("tri_period_no", sa.Integer(), nullable=True))
        t.add_column(sa.Column("tri_period_name", sa.String(32), nullable=False,
                               server_default=""))
        t.add_column(sa.Column("tri_class_names", sa.String(128), nullable=False,
                               server_default=""))
        t.add_column(sa.Column("tri_subject_name", sa.String(64), nullable=False,
                               server_default=""))
        t.add_column(sa.Column("tri_entry_id", sa.Integer(), nullable=True))
        t.create_foreign_key("fk_substitutions_tri_teacher", "teachers",
                             ["tri_teacher_id"], ["id"], ondelete="SET NULL")
        t.create_foreign_key("fk_substitutions_tri_entry", "schedule_entries",
                             ["tri_entry_id"], ["id"], ondelete="SET NULL")
        t.create_index("ix_substitutions_tri_teacher_id", ["tri_teacher_id"])


def downgrade() -> None:
    with op.batch_alter_table("substitutions") as t:
        t.drop_index("ix_substitutions_tri_teacher_id")
        t.drop_constraint("fk_substitutions_tri_entry", type_="foreignkey")
        t.drop_constraint("fk_substitutions_tri_teacher", type_="foreignkey")
        for c in ("tri_entry_id", "tri_subject_name", "tri_class_names", "tri_period_name",
                  "tri_period_no", "tri_date", "tri_teacher_id"):
            t.drop_column(c)
