"""發布新課表時,把調課的補課節次接到新課表(v1.4.18)。

調課記下補課那一節時,記的是「課表的哪一格」(`Substitution.swap_entry_id`)。
學期中重新發布課表,新課表的每一格都是新的一列,舊課表封存——補課那一節還指著
舊課表的格子,於是:

- 班級、教師的週課表、教師週總表、巡堂表、即時概況都畫不出補課那一節
  (它們只看已發布課表的格子);
- 調課清單以為那一節「還沒被拿去調」,同一節可能再換給別人。

組長回報(v1.4.18):先調課再改課表發布,週課表只有請假那一格變紅。

做法:發布時找出這學期所有調課,在新課表裡找「同一門課(配課)、同一天、
涵蓋那一節」的格子接過去。找不到代表新課表把那堂課移走了,補課那一節已經
沒有這門課——不猜,留著原樣,由 `unlinked_count` 數出來提醒組長重新處理。

升級時的一次性修正見 alembic `0020_relink_swaps`(同一套規則,以 SQL 寫成)。
三角調課(v1.4.20)另有中間那一節(`tri_entry_id`),同一套規則一起接。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry, Timetable


def _swaps(db: Session, semester_id: int) -> list[Substitution]:
    return list(db.scalars(
        select(Substitution).where(
            Substitution.semester_id == semester_id,
            Substitution.type == SubstitutionType.swap.value,
            Substitution.swap_date.is_not(None),
        )
    ))


def _find(entries: list[ScheduleEntry], period_no: int) -> ScheduleEntry | None:
    return next((e for e in entries if e.period_no <= period_no < e.period_no + e.span), None)


def relink(db: Session, timetable: Timetable) -> int:
    """把這學期調課的補課節次接到 `timetable` 的格子;回傳接上的筆數。呼叫端負責 commit。

    已經在這份課表上的不動;舊格子已被刪除(課表刪掉了)的找不到配課,也不動。
    """
    index: dict[tuple[int, int], list[ScheduleEntry]] = {}
    for e in db.scalars(select(ScheduleEntry).where(ScheduleEntry.timetable_id == timetable.id)):
        index.setdefault((e.course_assignment_id, e.weekday), []).append(e)

    def link(entry_id: int | None, on: date | None, period_no: int | None) -> int | None:
        """接到新課表的格子 id;不必接或接不上回 None。"""
        old = db.get(ScheduleEntry, entry_id) if entry_id else None
        if old is None or old.timetable_id == timetable.id or on is None:
            return None
        no = period_no if period_no is not None else old.period_no
        new = _find(index.get((old.course_assignment_id, on.isoweekday()), []), no)
        return new.id if new is not None else None

    moved = 0
    for sub in _swaps(db, timetable.semester_id):
        new_id = link(sub.swap_entry_id, sub.swap_date, sub.swap_period_no)
        if new_id is not None:
            if sub.swap_period_no is None:
                old = db.get(ScheduleEntry, sub.swap_entry_id)
                sub.swap_period_no = old.period_no if old else None
            sub.swap_entry_id = new_id
            moved += 1
        tri_id = link(sub.tri_entry_id, sub.tri_date, sub.tri_period_no)
        if tri_id is not None:
            sub.tri_entry_id = tri_id
    db.flush()
    return moved


def unlinked_count(db: Session, timetable: Timetable, today: date | None = None) -> int:
    """今天以後、仍有效的調課裡,補課那一節不在這份課表上的筆數(發布後提醒組長)。"""
    today = today or clock.school_today()
    rows = db.execute(
        select(Substitution.swap_entry_id, Substitution.tri_entry_id,
               Substitution.tri_teacher_id)
        .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            Substitution.semester_id == timetable.semester_id,
            Substitution.type == SubstitutionType.swap.value,
            Substitution.swap_date >= today,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
    ).all()
    if not rows:
        return 0
    ids = {i for r in rows for i in (r[0], r[1]) if i is not None}
    on_this = set(db.scalars(
        select(ScheduleEntry.id).where(
            ScheduleEntry.timetable_id == timetable.id, ScheduleEntry.id.in_(ids or [0]))
    ))
    # 三角調課兩格都要在新課表上才算接好;算一筆
    return sum(1 for swap_id, tri_id, tri_teacher in rows
               if swap_id not in on_this or (tri_teacher is not None and tri_id not in on_this))
