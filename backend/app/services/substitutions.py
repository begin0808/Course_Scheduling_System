"""調代課處置(M4-2,architecture.md §5.3)。

指派即生效:建立/更新處置 → 受影響節次轉『已確認』並記下處理教師 → 通知處理教師。
沒有邀請/婉拒;通知只是正式告知 +「確認收到」。

**補登**(v1.4.2,組長回報):臨時找人代課、事後才登記請假時,節次已經過了還是「待處理」。
這些節次可以補登處置,直接成為已完成並列入鐘點統計;**不通知**(老師已經去上過課了),
也**不能補登調課**(調課要安排之後的補課節次)。已處理過、已過去的節次仍然不能改或撤回。

各處置的鐘點:代課計、併班/自習/不處理不計(§5.4 月結)。
調課(swap)要驗兩位教師交換後都無衝突,拒絕時說出是誰在哪一節撞課。

**三角調課**(v1.4.20,給了 `tri_teacher_id`):乙來上請假那節、丙來上乙的 `tri_*` 那節、
甲回來上丙的 `swap_*` 那節。三格都要驗;成立時三位老師都收到通知,撤回時一起撤、都收到取消通知。
鐘點都不計(和互調一樣)。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Subject, Teacher
from app.models.leave import (
    SELF_PAID_LEAVE_TYPES,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
)
from app.models.notification import NotificationType
from app.models.substitution import (
    SUBSTITUTION_TYPE_CN,
    TYPES_WITH_HANDLER,
    Substitution,
    SubstitutionType,
)
from app.models.timetable import ScheduleEntry
from app.services import notifications
from app.services.availability import Availability
from app.services.swap_options import SwapChecker, block_periods, triangle_unit


class SubstitutionError(Exception):
    """處置不合法(呼叫端轉為 400/409)。"""


def _wd(weekday: int) -> str:
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


def _counts_default(sub_type: str) -> bool:
    return sub_type == SubstitutionType.substitute.value


def _funding_default(sub_type: str, leave_type: str) -> str:
    """沒填計費方式時的預設:事假(含家庭照顧假)請人代課由請假教師自付,其餘由學校經費支應。

    學校規定不一,畫面上可改;這裡只是讓通知單不會印空白。
    """
    if sub_type != SubstitutionType.substitute.value:
        return ""
    return "自費代課" if leave_type in SELF_PAID_LEAVE_TYPES else "公費代課"


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
    swap_period_no: int | None = None,
    availability: Availability | None = None,
    tri_teacher_id: int | None = None,
    tri_entry_id: int | None = None,
    tri_date: date | None = None,
    tri_period_no: int | None = None,
) -> Substitution:
    """對一個受影響節次做處置。呼叫端負責 commit。

    `tri_*` 給了就是三角調課(只限調課):丙(`tri_teacher_id`)來上乙的 `tri_entry_id` 那節,
    甲回來上丙的 `swap_entry_id` 那節。
    """
    if affected.status == AffectedStatus.cancelled.value:
        raise SubstitutionError("此節次已因銷假取消,無法處置")
    backfill = is_backfill(affected)
    if affected.status == AffectedStatus.completed.value or (
        clock.is_past_slot(affected.date, affected.end_time) and not backfill
    ):
        raise SubstitutionError("此節次已結束,無法變更處置")
    if backfill and affected.leave_request.status == LeaveStatus.cancelled.value:
        raise SubstitutionError("此假單已銷假")
    if (backfill and sub_type == SubstitutionType.swap.value
            and affected.leave_request.leave_type != LeaveType.swap_only.value):
        raise SubstitutionError(
            "這一節已經過了,請假的節次無法補登調課,請改登代課"
            "(沒請假、只是調課的,請用「新增調課(未請假)」補登)")
    if sub_type not in set(SubstitutionType):
        raise SubstitutionError(f"未知的處置方式:{sub_type}")
    if (affected.leave_request.leave_type == LeaveType.swap_only.value
            and sub_type != SubstitutionType.swap.value):
        raise SubstitutionError("沒有請假的調課只能選調課")

    av = availability or Availability(db, affected.semester_id)
    handler = _resolve_handler(db, affected, sub_type, handler_teacher_id, av)

    triangle = tri_teacher_id is not None
    if triangle and sub_type != SubstitutionType.swap.value:
        raise SubstitutionError("三角調課只能選調課")
    swap_fields: dict = {}
    if sub_type == SubstitutionType.swap.value and triangle:
        swap_fields = _validate_triangle(
            db, affected, handler, av,
            tri_teacher_id=tri_teacher_id, tri_entry_id=tri_entry_id, tri_date=tri_date,
            tri_period_no=tri_period_no, swap_entry_id=swap_entry_id, swap_date=swap_date,
            swap_period_no=swap_period_no)
    elif sub_type == SubstitutionType.swap.value:
        swap_fields = _validate_swap(
            db, affected, handler, swap_entry_id, swap_date, swap_period_no, av)

    counts = _counts_default(sub_type) if counts_toward_hours is None else counts_toward_hours

    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected.id))
    if sub is None:
        sub = Substitution(semester_id=affected.semester_id, affected_period_id=affected.id)
        db.add(sub)
    sub.type = sub_type
    sub.handler_teacher_id = handler.id if handler else None
    sub.counts_toward_hours = counts
    sub.funding_source = funding_source or _funding_default(
        sub_type, affected.leave_request.leave_type)
    sub.created_by_user_id = created_by_user_id
    sub.created_by_name = created_by_name
    if sub.is_triangle and sub.tri_teacher_id != tri_teacher_id:
        # 改派:原本三角調課的丙要知道不用來了
        _notify_tri_cancelled(db, affected, sub, created_by_name)
    for k, v in swap_fields.items():
        setattr(sub, k, v)
    if sub_type != SubstitutionType.swap.value:
        _clear_swap(sub)
    if not triangle:
        _clear_tri(sub)

    affected.status = AffectedStatus.resolved.value
    affected.handler_teacher_id = handler.id if handler else None
    db.flush()

    if handler is not None and not backfill:
        _notify_handler(db, affected, sub, handler)
    return sub


def is_backfill(affected: AffectedPeriod) -> bool:
    """已經過去、還沒處理的節次:現在指派就是補登(不通知)。

    請假的節次不能補登調課;「調課(未請假)」只能調課,補登的就是調課(v1.4.10)。
    """
    return affected.status == AffectedStatus.pending.value and clock.is_past_slot(
        affected.date, affected.end_time)


def update_billing(
    db: Session,
    periods: list[AffectedPeriod],
    *,
    funding_source: str,
    counts_toward_hours: bool | None,
) -> list[AffectedPeriod]:
    """修改代課的計費方式與是否計入鐘點(v1.4.4,組長回報:假別登錯,計費方式跟著帶錯)。

    代課老師不變,只改「怎麼付錢」,所以**已經過去的節次也可以改**——這是「過去的處置不能改」
    唯一的例外。不通知(只是記帳資訊)。只改處置為代課、且沒被銷假取消的節次。
    回傳實際改到的節次;一節都沒有時拋錯。呼叫端負責 commit。
    """
    changed: list[AffectedPeriod] = []
    for ap in periods:
        sub = ap.substitution
        if (sub is None or sub.type != SubstitutionType.substitute.value
                or ap.status == AffectedStatus.cancelled.value):
            continue
        sub.funding_source = funding_source
        if counts_toward_hours is not None:
            sub.counts_toward_hours = counts_toward_hours
        changed.append(ap)
    if not changed:
        raise SubstitutionError("沒有可以修改計費方式的代課節次")
    db.flush()
    return changed


@dataclass(frozen=True, slots=True)
class BatchSkip:
    """整批指派時沒派成的一節,以及原因(代課老師那節有課、節次已結束…)。"""

    affected_period_id: int
    date: date
    period_name: str
    class_names: str
    subject_name: str
    reason: str


def assign_batch(
    db: Session,
    leave: LeaveRequest,
    *,
    handler_teacher_id: int,
    funding_source: str,
    counts_toward_hours: bool | None,
    on_date: date | None,
    created_by_user_id: int | None,
    created_by_name: str,
) -> tuple[list[Substitution], list[BatchSkip]]:
    """把一張假單(或其中一天)還沒處理的節次,一次指派給同一位代課老師(#36)。

    導師請整天或好幾天假時,一節一節點同一位代課老師要點幾十次。這裡逐節沿用 `assign`
    ——檢查規則完全一樣——派得成的就派,派不成的(代課老師那一節自己有課)
    跳過並回報原因,由組長另外找人。已經過去、還沒處理的節次一併補登(不通知);
    已經處理過的節次不動。呼叫端負責 commit。
    """
    if leave.leave_type == LeaveType.swap_only.value:
        raise SubstitutionError("沒有請假的調課只能選調課,不能整批指派代課")
    pending = sorted(
        (
            ap for ap in leave.affected_periods
            if ap.status == AffectedStatus.pending.value
            and (on_date is None or ap.date == on_date)
        ),
        key=lambda ap: (ap.date, ap.period_no),
    )
    if not pending:
        raise SubstitutionError(
            "這一天沒有待處理的節次" if on_date else "這張假單沒有待處理的節次")

    done: list[Substitution] = []
    skipped: list[BatchSkip] = []
    for ap in pending:
        try:
            done.append(assign(
                db, ap,
                sub_type=SubstitutionType.substitute.value,
                handler_teacher_id=handler_teacher_id,
                counts_toward_hours=counts_toward_hours, funding_source=funding_source,
                swap_entry_id=None, swap_date=None,
                created_by_user_id=created_by_user_id, created_by_name=created_by_name,
            ))
        except SubstitutionError as exc:
            skipped.append(BatchSkip(
                affected_period_id=ap.id, date=ap.date, period_name=ap.period_name,
                class_names=ap.class_names, subject_name=ap.subject_name, reason=str(exc),
            ))
    return done, skipped


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

    if sub_type == SubstitutionType.merge.value:
        # 併班:接手的是這一節正在上自己班的老師(併到他班一起上),不必空堂,
        # 只要人在(v1.3.5 使用者定案;先前要求空堂,與「併到他班」的意思相反)
        if av.on_leave(teacher.id, affected.date, av.slot_of(affected)):
            raise SubstitutionError(
                f"{teacher.name} {affected.date} {affected.period_name} 當天也請假,無法併班")
    elif sub_type != SubstitutionType.swap.value:
        # 代課:接手者在該時段必須是空的(調課的衝突另由 _validate_swap 檢查)
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
    swap_period_no: int | None,
    av: Availability,
) -> dict:
    """調課:乙(handler)代甲請假那節;甲(請假教師)於 swap_date 補乙原本的 swap_entry。

    先驗組合本身成立(是已發布課表裡乙的課、日期星期相符),再交給 `SwapChecker`
    驗「乙能來、甲能補」——與「可對調節次」清單同一套規則,清單上的一定送得出去:
      ① 乙 在甲請假那節有空(沒課、沒請假、沒被安排代別班)
      ② swap_entry 確實是乙在已發布課表裡的課,且 swap_date 是那節課真的會上的日子;
         連堂格位以 swap_period_no 指定換其中哪一節(空 = 第一節)
      ③ 甲 在 swap_date 那節有空;乙那節沒請假、也沒已經換給別人;日期在學期內且還沒上過
    任一不成立即拒絕並指名道姓。
    """
    if handler is None:
        raise SubstitutionError("調課需要指定對調教師")
    if swap_entry_id is None or swap_date is None:
        raise SubstitutionError("調課需要指定對調的節次與補課日期")

    entry = db.get(ScheduleEntry, swap_entry_id)
    if entry is None or av.timetable is None or entry.timetable_id != av.timetable.id:
        raise SubstitutionError("找不到要對調的節次(需為已發布課表中的課)")
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
    if not av.entry_runs_on(entry, swap_date):
        week = "單週" if av.week_of(swap_date) == "odd" else "雙週"
        raise SubstitutionError(f"{swap_date} 是{week},那一週沒有這堂課(單雙週的課)")
    period_no = entry.period_no if swap_period_no is None else swap_period_no
    if period_no not in block_periods(av, entry):
        raise SubstitutionError("指定的節次不在這堂課的時段內")
    if swap_date == affected.date and period_no == affected.period_no:
        raise SubstitutionError("補課的節次不能是請假的同一節")

    swap_assignment = db.get(CourseAssignment, entry.course_assignment_id)
    if swap_assignment is None:
        raise SubstitutionError("要對調的節次已無對應配課")

    checker = SwapChecker(db, affected, av)
    blocked = checker.partner_blocker(handler)
    if blocked is not None:
        raise SubstitutionError(f"{blocked},無法對調")
    blocked = checker.option_blocker(handler, entry, swap_date, period_no)
    if blocked is not None:
        subj = db.get(Subject, swap_assignment.subject_id)
        raise SubstitutionError(blocked + (f"(對調的是{subj.name})" if subj else ""))

    subject = db.get(Subject, swap_assignment.subject_id)
    classes = "、".join(m.class_unit.name for m in swap_assignment.scheduling_unit.members)
    return {
        "swap_date": swap_date,
        "swap_period_no": period_no,
        "swap_period_name": _entry_period_name(av, entry, period_no),
        "swap_class_names": classes,
        "swap_subject_name": subject.name if subject else "",
        "swap_entry_id": entry.id,
    }


def _lesson_of(
    db: Session, av: Availability, affected: AffectedPeriod, unit_id: int,
    teacher: Teacher, entry_id: int | None, when: date | None, period_no: int | None,
    what: str,
) -> tuple[ScheduleEntry, int]:
    """三角調課的一格:確認是這個班、這位老師在已發布課表裡的課,日期星期相符。"""
    if entry_id is None or when is None:
        raise SubstitutionError(f"三角調課需要指定{what}")
    entry = db.get(ScheduleEntry, entry_id)
    if entry is None or av.timetable is None or entry.timetable_id != av.timetable.id:
        raise SubstitutionError(f"找不到{what}(需為已發布課表中的課)")
    a = entry.assignment
    if a.scheduling_unit_id != unit_id:
        raise SubstitutionError(f"{what}不是 {affected.class_names} 的課(三角調課只限同一個班)")
    if [t.teacher_id for t in a.teachers] != [teacher.id]:
        raise SubstitutionError(f"{what}不是 {teacher.name} 一個人上的課")
    if when.isoweekday() != entry.weekday:
        raise SubstitutionError(
            f"{when} 是 {_wd(when.isoweekday())},但{what}在 {_wd(entry.weekday)}")
    if not av.entry_runs_on(entry, when):
        raise SubstitutionError(f"{when} 那一週沒有{what}(單雙週的課)")
    no = entry.period_no if period_no is None else period_no
    if no not in block_periods(av, entry):
        raise SubstitutionError(f"指定的節次不在{what}的時段內")
    if when == affected.date and no == affected.period_no:
        raise SubstitutionError(f"{what}不能是請假的同一節")
    return entry, no


def _validate_triangle(
    db: Session,
    affected: AffectedPeriod,
    handler: Teacher | None,
    av: Availability,
    *,
    tri_teacher_id: int | None,
    tri_entry_id: int | None,
    tri_date: date | None,
    tri_period_no: int | None,
    swap_entry_id: int | None,
    swap_date: date | None,
    swap_period_no: int | None,
) -> dict:
    """三角調課(v1.4.20):三格與 `swap_options.triangle_search` 同一套規則。

      ① 乙(handler)在甲請假那節有空
      ② 乙的 tri 那一節讓得出來(沒停課、乙沒請假、沒拿去調過),丙那節有空
      ③ 丙的 swap 那一節,甲回得來(與互調的補課節次同一套檢查)
    """
    if handler is None:
        raise SubstitutionError("調課需要指定對調教師")
    unit_id, why = triangle_unit(db, affected)
    if unit_id is None:
        raise SubstitutionError(why)
    third = db.scalar(select(Teacher).where(
        Teacher.id == tri_teacher_id, Teacher.semester_id == affected.semester_id))
    if third is None:
        raise SubstitutionError("找不到三角調課的第三位老師")
    absent_id = affected.leave_request.teacher_id
    if third.id in (absent_id, handler.id):
        raise SubstitutionError("三角調課要三位不同的老師")

    mid, mid_no = _lesson_of(db, av, affected, unit_id, handler, tri_entry_id, tri_date,
                             tri_period_no, f"{handler.name}要讓出的那一節")
    makeup, makeup_no = _lesson_of(db, av, affected, unit_id, third, swap_entry_id, swap_date,
                                   swap_period_no, f"{third.name}要讓出的那一節")
    assert tri_date is not None and swap_date is not None

    checker = SwapChecker(db, affected, av)
    blocked = checker.partner_blocker(handler)
    if blocked is not None:
        raise SubstitutionError(f"{blocked},無法三角調課")
    for entry, when, no in ((mid, tri_date, mid_no), (makeup, swap_date, makeup_no)):
        if checker.out_of_reach(entry, when, no):
            raise SubstitutionError(
                f"{when} {_entry_period_name(av, entry, no)} 已經上過或不在學期內,無法調課")
    reason = checker.mid_reason(handler, third, mid, tri_date, mid_no)
    if reason:
        raise SubstitutionError(f"{tri_date} {_entry_period_name(av, mid, mid_no)} {reason}")
    blocked = checker.option_blocker(third, makeup, swap_date, makeup_no)
    if blocked is not None:
        raise SubstitutionError(blocked)

    def snap(entry: ScheduleEntry) -> tuple[str, str]:
        a = entry.assignment
        return ("、".join(m.class_unit.name for m in a.scheduling_unit.members),
                a.subject.name if a.subject else "")

    mid_classes, mid_subject = snap(mid)
    makeup_classes, makeup_subject = snap(makeup)
    return {
        "tri_teacher_id": third.id,
        "tri_date": tri_date,
        "tri_period_no": mid_no,
        "tri_period_name": _entry_period_name(av, mid, mid_no),
        "tri_class_names": mid_classes,
        "tri_subject_name": mid_subject,
        "tri_entry_id": mid.id,
        "swap_date": swap_date,
        "swap_period_no": makeup_no,
        "swap_period_name": _entry_period_name(av, makeup, makeup_no),
        "swap_class_names": makeup_classes,
        "swap_subject_name": makeup_subject,
        "swap_entry_id": makeup.id,
    }


def _entry_period_name(av: Availability, entry: ScheduleEntry, period_no: int) -> str:
    p = av.entry_period(entry, period_no)
    return p.name if p else f"第 {period_no} 格"


def _clear_swap(sub: Substitution) -> None:
    sub.swap_date = None
    sub.swap_period_no = None
    sub.swap_period_name = ""
    sub.swap_class_names = ""
    sub.swap_subject_name = ""
    sub.swap_entry_id = None


def _clear_tri(sub: Substitution) -> None:
    sub.tri_teacher_id = None
    sub.tri_date = None
    sub.tri_period_no = None
    sub.tri_period_name = ""
    sub.tri_class_names = ""
    sub.tri_subject_name = ""
    sub.tri_entry_id = None


def _notify_tri_cancelled(
    db: Session, affected: AffectedPeriod, sub: Substitution, actor_name: str
) -> None:
    """三角調課取消:丙不必來上乙那一節(乙、甲另有通知)。"""
    if sub.tri_teacher_id is None:
        return
    notifications.notify(
        db, semester_id=affected.semester_id, teacher_id=sub.tri_teacher_id,
        type=NotificationType.substitution_cancelled,
        title="原訂三角調課已取消",
        body=(f"{actor_name} 取消了 {affected.date} {affected.period_name} 的三角調課;"
              f"您不必於 {sub.tri_date} {sub.tri_period_name} 上"
              f"{sub.tri_class_names}的課,{sub.swap_date} {sub.swap_period_name} 照原課表上課"),
    )


def _notify_handler(
    db: Session, affected: AffectedPeriod, sub: Substitution, handler: Teacher
) -> None:
    absent = affected.leave_request.teacher
    type_cn = SUBSTITUTION_TYPE_CN[sub.type]
    where = f"{affected.date} {affected.period_name}({affected.class_names}{affected.subject_name})"
    if sub.is_triangle and sub.tri_teacher is not None:
        _notify_triangle(db, affected, sub, handler, sub.tri_teacher, where)
        return
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
    if sub.type == SubstitutionType.swap.value:
        # 調課多了一個要到場的人:請假的甲得回來補乙那節。只通知乙,甲就會漏掉補課。
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=absent.id,
            type=NotificationType.substitution_assigned,
            title=f"調課補課通知:{sub.swap_date} {sub.swap_period_name}",
            body=(
                f"{handler.name} 將於 {where} 代您上課;"
                f"請您於 {sub.swap_date} {sub.swap_period_name} 補上 {handler.name} 的"
                f"{sub.swap_class_names}{sub.swap_subject_name}"
            ),
        )


def _notify_triangle(
    db: Session, affected: AffectedPeriod, sub: Substitution, handler: Teacher, third: Teacher,
    where: str,
) -> None:
    """三角調課:三位老師各要去上一節,各收一則通知。"""
    absent = affected.leave_request.teacher
    mid = f"{sub.tri_date} {sub.tri_period_name}({sub.tri_class_names}{sub.tri_subject_name})"
    makeup = (f"{sub.swap_date} {sub.swap_period_name}"
              f"({sub.swap_class_names}{sub.swap_subject_name})")
    who = f"{absent.name}、{handler.name}、{third.name}"
    for teacher, title, body in (
        (handler, f"三角調課通知:{affected.date} {affected.period_name}",
         f"請於 {where} 上課(代 {absent.name});您 {mid} 那一節由 {third.name} 上"),
        (third, f"三角調課通知:{sub.tri_date} {sub.tri_period_name}",
         f"請於 {sub.tri_date} {sub.tri_period_name} 上課(代 {handler.name} 的"
         f"{sub.tri_class_names}{sub.tri_subject_name});您 {makeup} 那一節由 {absent.name} 上"),
        (absent, f"三角調課補課通知:{sub.swap_date} {sub.swap_period_name}",
         f"{handler.name} 將於 {where} 代您上課;請您於 {sub.swap_date} {sub.swap_period_name} "
         f"上 {third.name} 的{sub.swap_class_names}{sub.swap_subject_name}"),
    ):
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=teacher.id,
            type=NotificationType.substitution_assigned, title=title,
            body=f"{body}({who} 三人輪流換課)",
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
    if sub.is_triangle:
        _notify_tri_cancelled(db, affected, sub, actor_name)
    if sub.type == SubstitutionType.swap.value:
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=affected.leave_request.teacher_id,
            type=NotificationType.substitution_cancelled,
            title="原訂調課已取消",
            body=(
                f"{actor_name} 取消了 {affected.date} {affected.period_name} 的調課;"
                f"您不必於 {sub.swap_date} {sub.swap_period_name} 補課"
            ),
        )
    db.delete(sub)
    affected.status = AffectedStatus.pending.value
    affected.handler_teacher_id = None
    db.flush()
