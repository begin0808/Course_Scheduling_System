"""semesters、period_tables、periods 資料表

Revision ID: 0002_semester_period
Revises: 0001_users
Create Date: 2026-07-08
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_semester_period"
down_revision: str | None = "0001_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semesters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preparing"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_semesters"),
        sa.UniqueConstraint("academic_year", "term", name="uq_semesters_academic_year"),
    )

    op.create_table(
        "period_tables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("num_weekdays", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_period_tables"),
        sa.ForeignKeyConstraint(
            ["semester_id"], ["semesters.id"],
            name="fk_period_tables_semester_id_semesters", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_period_tables_semester_id", "period_tables", ["semester_id"])

    op.create_table(
        "periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_table_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("type", sa.String(length=20), nullable=False, server_default="regular"),
        sa.PrimaryKeyConstraint("id", name="pk_periods"),
        sa.ForeignKeyConstraint(
            ["period_table_id"], ["period_tables.id"],
            name="fk_periods_period_table_id_period_tables", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("period_table_id", "weekday", "period_no", name="uq_periods_cell"),
    )
    op.create_index("ix_periods_period_table_id", "periods", ["period_table_id"])


def downgrade() -> None:
    op.drop_index("ix_periods_period_table_id", table_name="periods")
    op.drop_table("periods")
    op.drop_index("ix_period_tables_semester_id", table_name="period_tables")
    op.drop_table("period_tables")
    op.drop_table("semesters")
