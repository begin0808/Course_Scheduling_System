"""代導(v1.4.0):導師請假那天,由誰代他帶班。

規則(2026-10-29 使用者定案):
- 以天為單位;半天假也要代導,統計時「全天」「半天」分開記,代導費由學校自己換算。
- 誰都能代導——代導不是上課,**有課的老師也可以**;只排除當天整天請假的人。
  人選依序列出:同年級導師 → 該班任課老師 → 其他老師。
- 多天的假可一次指派整段,也可逐天改派;也可以標記「不需代導」(例如整班校外教學)。
- 指派即生效並通知代導老師(與代課相同,沒有邀請/婉拒流程)。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedStatus,
    HomeroomCover,
    LeaveRequest,
    LeaveStatus,
)
from app.models.notification import NotificationType
from app.services import leaves, notifications

GROUP_SAME_GRADE = "same_grade_homeroom"  # 同年級導師
GROUP_CLASS_TEACHER = "class_teacher"     # 該班任課老師
GROUP_OTHER = "other"                     # 其他老師

GROUP_CN = {
    GROUP_SAME_GRADE: "同年級導師",
    GROUP_CLASS_TEACHER: "該班任課老師",
    GROUP_OTHER: "其他老師",
}


class CoverError(Exception):
    """代導處置不合法(呼叫端轉為 409)。"""


@dataclass(frozen=True, slots=True)
class CoverOption:
    teacher_id: int
    teacher_name: str
    group: str
    note: str  # 「702 導師」「教 701 國文」


@dataclass(frozen=True, slots=True)
class CoverSkip:
    """一次指派整段時沒派成的一天,以及原因。"""

    cover_id: int
    date: date
    class_name: str
    reason: str


def on_full_day_leave(db: Session, teacher_id: int, day: date) -> bool:
    """這位老師當天整天請假(半天假仍可代導另外半天,不排除)。"""
    rows = db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.teacher_id == teacher_id,
            LeaveRequest.status == LeaveStatus.registered.value,
            LeaveRequest.start_date <= day,
            LeaveRequest.end_date >= day,
        )
    )
    return any(leaves._leave_window(lv, day) == (None, None) for lv in rows)


def options(db: Session, cover: HomeroomCover) -> list[CoverOption]:
    """可代導的老師:同年級導師 → 該班任課老師 → 其他老師,每人只出現一次。"""
    absent_id = cover.leave_request.teacher_id
    teachers = {
        t.id: t for t in db.scalars(
            select(Teacher).where(Teacher.semester_id == cover.semester_id))
        if t.is_active and t.id != absent_id
        and not on_full_day_leave(db, t.id, cover.date)
    }

    out: list[CoverOption] = []
    seen: set[int] = set()

    same_grade = db.scalars(
        select(ClassUnit).where(
            ClassUnit.semester_id == cover.semester_id,
            ClassUnit.grade == cover.grade,
            ClassUnit.homeroom_teacher_id.isnot(None),
        ).order_by(ClassUnit.name)
    )
    for klass in same_grade:
        tid = klass.homeroom_teacher_id
        if tid in teachers and tid not in seen:
            seen.add(tid)
            out.append(CoverOption(tid, teachers[tid].name, GROUP_SAME_GRADE, f"{klass.name} 導師"))

    if cover.class_id is not None:
        taught: dict[int, list[str]] = {}
        rows = db.execute(
            select(AssignmentTeacher.teacher_id, Subject.name)
            .join(CourseAssignment,
                  AssignmentTeacher.course_assignment_id == CourseAssignment.id)
            .join(SchedulingUnitMember,
                  SchedulingUnitMember.scheduling_unit_id == CourseAssignment.scheduling_unit_id)
            .join(Subject, Subject.id == CourseAssignment.subject_id)
            .where(
                CourseAssignment.semester_id == cover.semester_id,
                SchedulingUnitMember.class_unit_id == cover.class_id,
            )
        ).all()
        for tid, subject in rows:
            names = taught.setdefault(tid, [])
            if subject not in names:
                names.append(subject)
        class_teachers = sorted(
            (tid for tid in taught if tid in teachers and tid not in seen),
            key=lambda tid: teachers[tid].name)
        for tid in class_teachers:
            seen.add(tid)
            out.append(CoverOption(
                tid, teachers[tid].name, GROUP_CLASS_TEACHER,
                f"教 {cover.class_name} {'、'.join(taught[tid])}"))

    for t in sorted(teachers.values(), key=lambda t: t.name):
        if t.id not in seen:
            out.append(CoverOption(t.id, t.name, GROUP_OTHER, ""))
    return out


def is_backfill(cover: HomeroomCover) -> bool:
    """已經過去、還沒安排的代導:現在指派就是補登(v1.4.2,不通知)。"""
    return cover.status == AffectedStatus.pending.value and leaves.cover_is_past(cover.date)


def _check_open(cover: HomeroomCover, *, allow_backfill: bool = False) -> None:
    if cover.status == AffectedStatus.cancelled.value:
        raise CoverError("這一天的代導已因銷假取消")
    if leaves.cover_is_past(cover.date) and not (allow_backfill and is_backfill(cover)):
        raise CoverError("這一天已經過了,無法變更代導")
    if cover.leave_request.status == LeaveStatus.cancelled.value:
        raise CoverError("此假單已銷假")


def _handler(db: Session, cover: HomeroomCover, teacher_id: int) -> Teacher:
    teacher = db.scalar(
        select(Teacher).where(Teacher.id == teacher_id, Teacher.semester_id == cover.semester_id))
    if teacher is None:
        raise CoverError("找不到指定的教師")
    if teacher.id == cover.leave_request.teacher_id:
        raise CoverError("不能指派請假的導師代導自己的班")
    if on_full_day_leave(db, teacher.id, cover.date):
        raise CoverError(f"{teacher.name} {cover.date} 整天請假,無法代導")
    return teacher


def _set(db: Session, cover: HomeroomCover, handler: Teacher | None, actor_name: str) -> None:
    previous = cover.handler_teacher_id
    if previous is not None and previous != (handler.id if handler else None):
        _notify_cancelled(db, cover, previous, actor_name)
    cover.status = AffectedStatus.resolved.value
    cover.no_cover = handler is None
    cover.handler_teacher_id = handler.id if handler else None
    cover.assigned_by_name = actor_name
    # 補登(那天已經過了)不通知:老師已經代導過了
    if handler is not None and previous != handler.id and not leaves.cover_is_past(cover.date):
        absent = cover.leave_request.teacher
        notifications.notify(
            db, semester_id=cover.semester_id, teacher_id=handler.id,
            type=NotificationType.substitution_assigned,
            title=f"代導通知:{cover.date}({cover.part_label})",
            body=(f"請於 {cover.date}({cover.part_label})"
                  f"代 {absent.name} 擔任 {cover.class_name} 導師"),
        )


def _notify_cancelled(db: Session, cover: HomeroomCover, teacher_id: int, actor_name: str) -> None:
    notifications.notify(
        db, semester_id=cover.semester_id, teacher_id=teacher_id,
        type=NotificationType.substitution_cancelled,
        title="原訂代導已取消",
        body=f"{actor_name} 取消了 {cover.date}({cover.part_label}){cover.class_name} 的代導",
    )


def assign(
    db: Session,
    cover: HomeroomCover,
    *,
    handler_teacher_id: int | None,
    no_cover: bool,
    whole_leave: bool,
    actor_name: str,
) -> tuple[list[HomeroomCover], list[CoverSkip]]:
    """指派代導老師,或標記「不需代導」。呼叫端負責 commit。

    `whole_leave`:同一張假單、同一班其他還沒安排的日子一起指派(多天的假一次派完)。
    派不成的日子(那位老師當天整天請假)跳過並回報原因,仍維持待代導。
    """
    _check_open(cover, allow_backfill=True)
    handler: Teacher | None = None
    if not no_cover:
        if handler_teacher_id is None:
            raise CoverError("請選擇代導老師")
        handler = _handler(db, cover, handler_teacher_id)
    _set(db, cover, handler, actor_name)
    done = [cover]

    skipped: list[CoverSkip] = []
    if whole_leave:
        rest = [
            c for c in cover.leave_request.homeroom_covers
            if c.id != cover.id and c.class_name == cover.class_name
            and c.status == AffectedStatus.pending.value
        ]
        for c in rest:
            if handler is not None and on_full_day_leave(db, handler.id, c.date):
                skipped.append(CoverSkip(c.id, c.date, c.class_name,
                                         f"{handler.name} 當天整天請假"))
                continue
            _set(db, c, handler, actor_name)
            done.append(c)
    db.flush()
    return done, skipped


def clear(db: Session, cover: HomeroomCover, *, actor_name: str) -> None:
    """撤回:退回「待代導」,原代導老師收到取消通知。呼叫端負責 commit。"""
    _check_open(cover)
    if cover.handler_teacher_id is not None:
        _notify_cancelled(db, cover, cover.handler_teacher_id, actor_name)
    cover.status = AffectedStatus.pending.value
    cover.no_cover = False
    cover.handler_teacher_id = None
    cover.assigned_by_name = ""
    db.flush()


def query(
    db: Session,
    semester_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    teacher_id: int | None = None,
) -> list[HomeroomCover]:
    """代導紀錄:依日期區間、教師(請假的導師或代導老師)篩選,未銷假的才列。"""
    stmt = (
        select(HomeroomCover)
        .join(LeaveRequest, HomeroomCover.leave_request_id == LeaveRequest.id)
        .where(
            HomeroomCover.semester_id == semester_id,
            HomeroomCover.status != AffectedStatus.cancelled.value,
        )
    )
    if date_from is not None:
        stmt = stmt.where(HomeroomCover.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(HomeroomCover.date <= date_to)
    if teacher_id is not None:
        stmt = stmt.where(
            (LeaveRequest.teacher_id == teacher_id)
            | (HomeroomCover.handler_teacher_id == teacher_id))
    return list(db.scalars(
        stmt.order_by(HomeroomCover.date.desc(), HomeroomCover.class_name)).unique())


@dataclass(frozen=True, slots=True)
class SlipRow:
    date: date
    weekday: int
    part_label: str
    class_name: str
    absent_teacher_name: str
    leave_type_label: str


@dataclass(frozen=True, slots=True)
class Slip:
    """代導通知單:一位代導老師一張,列出他要代導的每一天。"""

    teacher_name: str
    rows: list[SlipRow]


def slips(db: Session, semester_id: int, cover_ids: list[int]) -> list[Slip]:
    covers = db.scalars(
        select(HomeroomCover).where(
            HomeroomCover.semester_id == semester_id,
            HomeroomCover.id.in_(cover_ids),
            HomeroomCover.status != AffectedStatus.cancelled.value,
            HomeroomCover.handler_teacher_id.isnot(None),
        )
    ).all()
    by_teacher: dict[str, list[SlipRow]] = {}
    for c in covers:
        if c.handler is None:
            continue
        leave = c.leave_request
        by_teacher.setdefault(c.handler.name, []).append(SlipRow(
            date=c.date, weekday=c.weekday, part_label=c.part_label, class_name=c.class_name,
            absent_teacher_name=leave.teacher.name,
            leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
        ))
    return [
        Slip(teacher_name=name, rows=sorted(rows, key=lambda r: (r.date, r.class_name)))
        for name, rows in sorted(by_teacher.items())
    ]
