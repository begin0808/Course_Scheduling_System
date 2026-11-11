"""v1.4.18:調課的補課節次接回目前已發布的課表(只修資料,不改資料表)。

調課記下補課那一節時記的是「課表的哪一格」。v1.4.17 以前,學期中重新發布課表後,
補課那一節還指著舊課表(已封存)的格子:週課表、巡堂表畫不出補課那一節,調課清單
也以為那一節還能再拿去調。v1.4.18 起發布時會自動接過去(`app.services.swap_relink`);
這裡把升級前已經發生的接回來,規則相同:目前已發布課表裡「同一門課(配課)、同一天、
涵蓋那一節」的格子。找不到的(新課表把那堂課移走了)維持原樣。

Revision ID: 0020_relink_swaps
Revises: 0019_homeroom_covers
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "0020_relink_swaps"
down_revision = "0019_homeroom_covers"
branch_labels = None
depends_on = None


def _weekday(value) -> int:
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return d.isoweekday()


def relink(conn) -> int:
    """回傳接上的筆數(測試也直接呼叫)。"""
    rows = conn.execute(sa.text(
        """
        SELECT s.id, s.swap_date, s.swap_period_no, oe.course_assignment_id, oe.period_no,
               tp.id AS published_id
        FROM substitutions s
        JOIN schedule_entries oe ON oe.id = s.swap_entry_id
        JOIN timetables tp ON tp.semester_id = s.semester_id AND tp.status = 'published'
        WHERE s.type = 'swap' AND s.swap_date IS NOT NULL AND oe.timetable_id <> tp.id
        """
    )).all()
    moved = 0
    for sub_id, swap_date, swap_period_no, assignment_id, old_period_no, published_id in rows:
        period_no = swap_period_no if swap_period_no is not None else old_period_no
        new_id = conn.execute(sa.text(
            """
            SELECT id FROM schedule_entries
            WHERE timetable_id = :tt AND course_assignment_id = :a AND weekday = :wd
              AND period_no <= :p AND :p < period_no + span
            ORDER BY id LIMIT 1
            """
        ), {"tt": published_id, "a": assignment_id, "wd": _weekday(swap_date),
            "p": period_no}).scalar()
        if new_id is None:
            continue
        conn.execute(sa.text(
            "UPDATE substitutions SET swap_entry_id = :e, swap_period_no = :p WHERE id = :i"
        ), {"e": new_id, "p": period_no, "i": sub_id})
        moved += 1
    return moved


def upgrade() -> None:
    relink(op.get_bind())


def downgrade() -> None:
    # 接到新課表的格子是正確的資料,不還原
    pass
