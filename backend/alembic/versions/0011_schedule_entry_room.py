"""課表格位的實際場地:schedule_entries.room_id

空 = 沿用配課的 room_id。排課引擎對「只指定場地類型」的配課逐格挑教室,
結果需存在格位上(M4 調代課的教室異動亦然)。

Revision ID: 0011_schedule_entry_room
Revises: 0010_audit_logs
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_schedule_entry_room"
down_revision: str | None = "0010_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schedule_entries", sa.Column("room_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_schedule_entries_room_id_rooms",
        "schedule_entries",
        "rooms",
        ["room_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_schedule_entries_room_id", "schedule_entries", ["room_id"])


def downgrade() -> None:
    op.drop_index("ix_schedule_entries_room_id", table_name="schedule_entries")
    op.drop_constraint("fk_schedule_entries_room_id_rooms", "schedule_entries", type_="foreignkey")
    op.drop_column("schedule_entries", "room_id")
