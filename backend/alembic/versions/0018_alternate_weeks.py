"""v1.3.0:單雙週課程。

配課多一欄 `week_parity`:空 = 每週都上(既有的所有配課都是這個值,行為完全不變);
odd/even = 只在單週/雙週上。單雙週的兩筆配課放在同一個「單雙週組」
(scheduling_units.unit_type = 'alternate',沿用既有欄位,不需改表)。

只新增一個可為空的欄位,不改既有資料:從任何 v1.2.x 升上來,所有課表、請假、
代課紀錄都照舊。

Revision ID: 0018_alternate_weeks
Revises: 0017_class_name_unique
"""

import sqlalchemy as sa

from alembic import op

revision = "0018_alternate_weeks"
down_revision = "0017_class_name_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_assignments",
        sa.Column("week_parity", sa.String(length=4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("course_assignments", "week_parity")
