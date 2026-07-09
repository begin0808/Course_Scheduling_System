"""class_units 增加 period_table_id(所屬節次表)

Revision ID: 0006_class_period_table
Revises: 0005_wizard_state
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_class_period_table"
down_revision: str | None = "0005_wizard_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("class_units", sa.Column("period_table_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_class_units_period_table_id_period_tables",
        "class_units", "period_tables",
        ["period_table_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_class_units_period_table_id", "class_units", ["period_table_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_class_units_period_table_id", table_name="class_units")
    op.drop_constraint(
        "fk_class_units_period_table_id_period_tables", "class_units", type_="foreignkey"
    )
    op.drop_column("class_units", "period_table_id")
