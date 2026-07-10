"""課表版本服務:完整性檢查、複製草稿、發布(architecture.md D4)。

發布 = draft → published;同學期原有的 published 自動轉 archived(僅一份 published)。
發布為快照:已發布/已封存的課表不可再編輯格位(見 api/timetables._require_draft)。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.audit import AuditLog
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import User


def completeness(db: Session, timetable: Timetable) -> dict:
    """比對每筆配課的每週節數與已排入節數,回傳未排完清單(H8 週節數守恆的發布面檢查)。"""
    placed_rows = db.execute(
        select(ScheduleEntry.course_assignment_id, func.sum(ScheduleEntry.span))
        .where(ScheduleEntry.timetable_id == timetable.id)
        .group_by(ScheduleEntry.course_assignment_id)
    ).all()
    placed_by = {aid: int(n or 0) for aid, n in placed_rows}

    assignments = db.scalars(
        select(CourseAssignment)
        .where(CourseAssignment.semester_id == timetable.semester_id)
        .order_by(CourseAssignment.id)
    ).all()

    unplaced = []
    required = 0
    placed_total = 0
    for a in assignments:
        required += a.periods_per_week
        placed = placed_by.get(a.id, 0)
        placed_total += placed
        if placed < a.periods_per_week:
            unplaced.append({
                "course_assignment_id": a.id,
                "subject": a.subject.name,
                "classes": [m.class_unit.name for m in a.scheduling_unit.members],
                "teachers": [at.teacher.name for at in a.teachers],
                "required": a.periods_per_week,
                "placed": placed,
                "remaining": a.periods_per_week - placed,
            })
    return {
        "required": required,
        "placed": placed_total,
        "remaining": max(required - placed_total, 0),
        "complete": not unplaced,
        "unplaced": unplaced,
    }


def duplicate(db: Session, source: Timetable, name: str) -> Timetable:
    """複製為新草稿(含全部格位與鎖定狀態);兩份草稿完全獨立。"""
    new = Timetable(semester_id=source.semester_id, name=name,
                    status=TimetableStatus.draft.value)
    db.add(new)
    db.flush()
    entries = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == source.id)
    ).all()
    for e in entries:
        db.add(ScheduleEntry(
            timetable_id=new.id, course_assignment_id=e.course_assignment_id,
            weekday=e.weekday, period_no=e.period_no, span=e.span, locked=e.locked,
            room_id=e.room_id,
        ))
    db.flush()
    return new


def publish(db: Session, timetable: Timetable, user: User, forced: bool) -> Timetable:
    """draft → published;同學期原 published 轉 archived。呼叫端負責 commit。"""
    previous = db.scalars(
        select(Timetable).where(
            Timetable.semester_id == timetable.semester_id,
            Timetable.status == TimetableStatus.published.value,
            Timetable.id != timetable.id,
        )
    ).all()
    for p in previous:
        p.status = TimetableStatus.archived.value
    timetable.status = TimetableStatus.published.value

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="publish_timetable", target_type="timetable", target_id=timetable.id,
        detail=(
            f"發布課表「{timetable.name}」"
            + (f",同時封存「{'、'.join(p.name for p in previous)}」" if previous else "")
            + ("(含未排完課務,強制發布)" if forced else "")
        )[:500],
    ))
    db.flush()
    return timetable
