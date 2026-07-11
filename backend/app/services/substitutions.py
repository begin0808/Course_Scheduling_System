"""調代課處置(M4-2,architecture.md §5.3)。

指派即生效:建立/更新處置 → 受影響節次轉『已確認』並記下處理教師 → 通知處理教師。
沒有邀請/婉拒;通知只是正式告知 +「確認收到」。

各處置的鐘點:代課計、併班/自習/不處理不計(§5.4 月結)。
調課(swap)要驗兩位教師交換後都無衝突,拒絕時說出是誰在哪一節撞課。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Subject, Teacher
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveStatus
from app.models.notification import NotificationType
from app.models.substitution import (
    SUBSTITUTION_TYPE_CN,
    TYPES_WITH_HANDLER,
    Substitution,
    SubstitutionType,
)
from app.models.timetable import ScheduleEntry
from app.services import notifications
from app.services.availability import Availability, Interval


class SubstitutionError(Exception):
    """處置不合法(呼叫端轉為 400/409)。"""


def _wd(weekday: int) -> str:
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


def _counts_default(sub_type: str) -> bool:
    return sub_type == SubstitutionType.substitute.value


def assign(
    db: Session,
    affected: AffectedPeriod,
    *,
    sub_type: str,
    handler_teacher_id: int | None,
    counts_toward_hours: bool | None,
    funding_source: str,
    swap_entry_id: int | None,
    swap_date: date | None,
    created_by_user_id: int | None,
    created_by_name: str,
    availability: Availability | None = None,
) -> Substitution:
    """對一個受影響節次做處置。呼叫端負責 commit。"""
    if affected.status == AffectedStatus.cancelled.value:
        raise SubstitutionError("此節次已因銷假取消,無法處置")
    if affected.status == AffectedStatus.completed.value or clock.is_past_slot(
        affected.date, affected.end_time
    ):
        raise SubstitutionError("此節次已結束,無法變更處置")
    if sub_type not in set(SubstitutionType):
        raise SubstitutionError(f"未知的處置方式:{sub_type}")

    av = availability or Availability(db, affected.semester_id)
    handler = _resolve_handler(db, affected, sub_type, handler_teacher_id, av)

    swap_fields: dict = {}
    if sub_type == SubstitutionType.swap.value:
        swap_fields = _validate_swap(db, affected, handler, swap_entry_id, swap_date, av)

    counts = _counts_default(sub_type) if counts_toward_hours is None else counts_toward_hours

    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected.id))
    if sub is None:
        sub = Substitution(semester_id=affected.semester_id, affected_period_id=affected.id)
        db.add(sub)
    sub.type = sub_type
    sub.handler_teacher_id = handler.id if handler else None
    sub.counts_toward_hours = counts
    sub.funding_source = funding_source
    sub.created_by_user_id = created_by_user_id
    sub.created_by_name = created_by_name
    for k, v in swap_fields.items():
        setattr(sub, k, v)
    if sub_type != SubstitutionType.swap.value:
        _clear_swap(sub)

    affected.status = AffectedStatus.resolved.value
    affected.handler_teacher_id = handler.id if handler else None
    db.flush()

    if handler is not None:
        _notify_handler(db, affected, sub, handler)
    return sub


def _resolve_handler(
    db: Session,
    affected: AffectedPeriod,
    sub_type: str,
    handler_teacher_id: int | None,
    av: Availability,
) -> Teacher | None:
    if sub_type not in TYPES_WITH_HANDLER:
        return None  # 自習/不處理沒有處理教師
    if handler_teacher_id is None:
        raise SubstitutionError(f"「{SUBSTITUTION_TYPE_CN[sub_type]}」需要指定教師")

    teacher = db.scalar(
        select(Teacher).where(
            Teacher.id == handler_teacher_id, Teacher.semester_id == affected.semester_id
        )
    )
    if teacher is None:
        raise SubstitutionError("找不到指定的教師")
    if teacher.id == affected.leave_request.teacher_id:
        raise SubstitutionError("不能指派請假教師代自己的課")

    # 代課/併班:接手者在該時段必須是空的(調課的衝突另由 _validate_swap 檢查)
    if sub_type != SubstitutionType.swap.value:
        conflict = av.conflict_for(teacher.id, affected.date, av.slot_of(affected))
        if conflict is not None:
            raise SubstitutionError(
                f"{teacher.name} {affected.date} {affected.period_name} {conflict.detail},無法指派"
            )
    return teacher


def _validate_swap(
    db: Session,
    affected: AffectedPeriod,
    handler: Teacher | None,
    swap_entry_id: int | None,
    swap_date: date | None,
    av: Availability,
) -> dict:
    """調課:乙(handler)代甲請假那節;甲(請假教師)於 swap_date 補乙原本的 swap_entry。

    驗四件事,任一撞課即拒絕並指名道姓:
      ① 乙 在甲請假那節無自己的課    ② swap_entry 確實是乙的課
      ③ 甲 在 swap_date 那節無課、也沒請假   ④ swap_date 是乙該節課真的會上的日子
    """
    if handler is None:
        raise SubstitutionError("調課需要指定對調教師")
    if swap_entry_id is None or swap_date is None:
        raise SubstitutionError("調課需要指定對調的節次與補課日期")

    entry = db.get(ScheduleEntry, swap_entry_id)
    if entry is None:
        raise SubstitutionError("找不到要對調的節次")
    teaches = db.scalar(
        select(AssignmentTeacher).where(
            AssignmentTeacher.course_assignment_id == entry.course_assignment_id,
            AssignmentTeacher.teacher_id == handler.id,
        )
    )
    if teaches is None:
        raise SubstitutionError(f"要對調的節次不是 {handler.name} 的課")
    if swap_date.isoweekday() != entry.weekday:
        raise SubstitutionError(
            f"{swap_date} 是 {_wd(swap_date.isoweekday())},"
            f"但對調的課在 {_wd(entry.weekday)},補課日期與該節課星期不符"
        )

    # ① 乙 在甲請假那節不能有自己的課(代課要來上)
    clash = av.teaching_at(handler.id, av.slot_of(affected))
    if clash is not None:
        raise SubstitutionError(
            f"{handler.name} {affected.date} {affected.period_name} 有自己的課,無法對調"
        )

    swap_assignment = db.get(CourseAssignment, entry.course_assignment_id)
    if swap_assignment is None:
        raise SubstitutionError("要對調的節次已無對應配課")

    # ③ 甲 在 swap_date 的 swap 節次不能有課、也不能請假
    absent = affected.leave_request.teacher
    swap_slot = Interval(entry.weekday, entry.period_no, None, None)
    conflict = av.conflict_for(absent.id, swap_date, swap_slot)
    if conflict is not None:
        subj = db.get(Subject, swap_assignment.subject_id)
        pname = _entry_period_name(db, entry)
        raise SubstitutionError(
            f"{absent.name} 無法在 {swap_date} {pname} 補課:{conflict.detail}"
            + (f"(對調的是{subj.name})" if subj else "")
        )

    subject = db.get(Subject, swap_assignment.subject_id)
    classes = "、".join(m.class_unit.name for m in swap_assignment.scheduling_unit.members)
    return {
        "swap_date": swap_date,
        "swap_period_no": entry.period_no,
        "swap_period_name": _entry_period_name(db, entry),
        "swap_class_names": classes,
        "swap_subject_name": subject.name if subject else "",
        "swap_entry_id": entry.id,
    }


def _entry_period_name(db: Session, entry: ScheduleEntry) -> str:
    from app.models.period import Period

    a = db.get(CourseAssignment, entry.course_assignment_id)
    if a and a.scheduling_unit.members:
        from app.services import period_tables as pt_service

        table = pt_service.resolve_period_table(db, a.scheduling_unit.members[0].class_unit)
        if table:
            p = db.scalar(select(Period).where(
                Period.period_table_id == table.id,
                Period.weekday == entry.weekday, Period.period_no == entry.period_no,
            ))
            if p:
                return p.name
    return f"第 {entry.period_no} 格"


def _clear_swap(sub: Substitution) -> None:
    sub.swap_date = None
    sub.swap_period_no = None
    sub.swap_period_name = ""
    sub.swap_class_names = ""
    sub.swap_subject_name = ""
    sub.swap_entry_id = None


def _notify_handler(
    db: Session, affected: AffectedPeriod, sub: Substitution, handler: Teacher
) -> None:
    absent = affected.leave_request.teacher
    type_cn = SUBSTITUTION_TYPE_CN[sub.type]
    where = f"{affected.date} {affected.period_name}({affected.class_names}{affected.subject_name})"
    if sub.type == SubstitutionType.swap.value:
        body = (
            f"請於 {where} 代 {absent.name} 一節;"
            f"{absent.name} 將於 {sub.swap_date} {sub.swap_period_name} 補您的"
            f"{sub.swap_class_names}{sub.swap_subject_name}"
        )
    else:
        body = f"請於 {where} {type_cn} {absent.name} 的課"
    notifications.notify(
        db, semester_id=affected.semester_id, teacher_id=handler.id,
        type=NotificationType.substitution_assigned,
        title=f"{type_cn}通知:{affected.date} {affected.period_name}",
        body=body,
    )


def clear(db: Session, affected: AffectedPeriod, *, actor_name: str) -> None:
    """撤回處置:受影響節次退回『待處理』,已指派的教師收到取消通知。呼叫端負責 commit。"""
    if affected.leave_request.status == LeaveStatus.cancelled.value:
        raise SubstitutionError("此假單已銷假")
    if clock.is_past_slot(affected.date, affected.end_time):
        raise SubstitutionError("此節次已結束,無法撤回處置")
    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected.id))
    if sub is None:
        return
    if sub.handler_teacher_id is not None:
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=sub.handler_teacher_id,
            type=NotificationType.substitution_cancelled,
            title=f"原訂{SUBSTITUTION_TYPE_CN[sub.type]}已取消",
            body=f"{actor_name} 取消了 {affected.date} {affected.period_name} 的處置",
        )
    db.delete(sub)
    affected.status = AffectedStatus.pending.value
    affected.handler_teacher_id = None
    db.flush()
