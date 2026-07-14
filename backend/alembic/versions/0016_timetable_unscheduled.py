"""M6-3:部分排課的未排清單隨草稿持久化。

先前未排清單只活在 Redis(24h TTL):部分排課草稿被 force 發布之後,solver 說「這幾門
課排不下、原因是什麼」的紀錄就消失了。哪些配課還缺節數可由 completeness 從 DB 重算,
但**原因**只有 solver 知道,不存就永遠遺失。

Revision ID: 0016_timetable_unscheduled
Revises: 0015_app_settings
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_timetable_unscheduled"
down_revision = "0015_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "timetables",
        sa.Column(
            "unscheduled",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("timetables", "unscheduled")
