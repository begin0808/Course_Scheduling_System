"""M6-5:同學期班名唯一。

衝突訊息、課表、匯出全都以班名指稱班級——同學期出現兩個「301」時,組長在畫面上根本
分不出是哪一班。加約束前必須先處理既有的重複資料,否則有重複班名的學校升級會直接失敗
(而他們正是最需要這個約束的人)。重複者依 id 順序改名為「301 (2)」「301 (3)」…,
不刪任何資料,課表與配課全部保留;組長升級後可自行改成正確的班名。

Revision ID: 0017_class_name_unique
Revises: 0016_timetable_unscheduled
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_class_name_unique"
down_revision = "0016_timetable_unscheduled"
branch_labels = None
depends_on = None


def _dedupe_existing_names(conn) -> None:
    rows = conn.execute(
        sa.text(
            """
            SELECT id, semester_id, name FROM class_units c
            WHERE EXISTS (
                SELECT 1 FROM class_units o
                WHERE o.semester_id = c.semester_id AND o.name = c.name AND o.id <> c.id
            )
            ORDER BY semester_id, name, id
            """
        )
    ).all()

    seen: dict[tuple[int, str], int] = {}
    for row_id, semester_id, name in rows:
        key = (semester_id, name)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 1:
            continue  # 第一筆保留原名
        # 找一個還沒被用掉的名字(理論上 (2) 就夠,但不排除學校自己已經有「301 (2)」)
        suffix = seen[key]
        while True:
            candidate = f"{name} ({suffix})"
            taken = conn.execute(
                sa.text(
                    "SELECT 1 FROM class_units "
                    "WHERE semester_id = :sid AND name = :n LIMIT 1"
                ),
                {"sid": semester_id, "n": candidate},
            ).first()
            if not taken:
                break
            suffix += 1
        conn.execute(
            sa.text("UPDATE class_units SET name = :n WHERE id = :i"),
            {"n": candidate, "i": row_id},
        )


def upgrade() -> None:
    _dedupe_existing_names(op.get_bind())
    op.create_unique_constraint(
        "uq_class_units_semester_name", "class_units", ["semester_id", "name"]
    )


def downgrade() -> None:
    # 改過的班名不還原(無法分辨哪些是升級改的、哪些是組長自己取的)
    op.drop_constraint("uq_class_units_semester_name", "class_units", type_="unique")
