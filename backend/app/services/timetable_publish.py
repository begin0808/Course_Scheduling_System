"""課表版本服務:完整性檢查、複製草稿、發布(architecture.md D4)。

發布 = draft → published;同學期原有的 published 自動轉 archived(僅一份 published)。
發布為快照:已發布/已封存的課表不可再編輯格位(見 api/timetables._require_draft)。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import CourseAssignment
from app.models.audit import AuditLog
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import User


def _reasons_by_assignment(timetable: Timetable) -> dict[int, str]:
    """把該課表存下的 solver 未排原因攤成 {配課 id: 原因}(M6-3)。

    「哪些配課還缺節數」一律由下方 completeness 從 DB 重算——那是唯一真相,連手動改過
    的課表都算得對。這裡只補上 DB 推導不出來的那一半:**為什麼排不下**。
    """
    out: dict[int, str] = {}
    for item in timetable.unscheduled or []:
        reason = item.get("reason") or ""
        if not reason:
            continue
        for aid in item.get("assignment_ids", []):
            out[aid] = reason
    return out


def completeness(db: Session, timetable: Timetable) -> dict:
    """比對每筆配課的每週節數與已排入節數,回傳未排完清單(H8 週節數守恆的發布面檢查)。"""
    reasons = _reasons_by_assignment(timetable)
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
                "reason": reasons.get(a.id, ""),
            })
    return {
        "required": required,
        "placed": placed_total,
        "remaining": max(required - placed_total, 0),
        "complete": not unplaced,
        "unplaced": unplaced,
    }


def stale_future_affected_count(db: Session, semester_id: int) -> int:
    """今日之後仍待處理/已指派的受影響節次數。

    這些節次的快照是依**先前**已發布課表展開的;學期中重新發布課表後,它們可能指向
    已移走的格位(代課老師被派去上一節新課表裡不存在的課)。回傳數量供發布後提醒組長
    重新檢視。完整解(重跑 expand + diff + 通知)見 tasks.md M5-0 條件 D。
    """
    return db.scalar(
        select(func.count())
        .select_from(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester_id,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status.in_(
                [AffectedStatus.pending.value, AffectedStatus.resolved.value]
            ),
            AffectedPeriod.date >= clock.school_today(),
        )
    ) or 0


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
