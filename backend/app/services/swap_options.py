"""調課:可對調節次的搜尋與逐項檢查(v1.2.1)。

調課的語意見 `models/substitution.py`:甲請假那節由乙來上,甲之後補乙的一節。
後端 M4-2 只會「驗」組長選好的組合;但組長不會自己去翻乙哪一節、哪一天能換——
這裡替他列出**本週與下週**所有真的換得成的組合。

**列出的與送出時驗的必須是同一套規則**,否則清單上點得到、按下去卻被拒絕。
所以逐項檢查集中在 `SwapChecker`,`substitutions._validate_swap` 也呼叫它。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment, SchedulingUnitMember
from app.models.basedata import Teacher
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import PeriodType
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services.availability import Availability


def _period_label(av: Availability, entry: ScheduleEntry, period_no: int) -> str:
    p = av.entry_period(entry, period_no)
    return p.name if p else f"第 {period_no} 格"


def block_periods(av: Availability, entry: ScheduleEntry) -> list[int]:
    """格位佔用的每一節中,可以拿來對調的節次號。

    連堂一次佔好幾節,但補課是一節換一節:乙連堂中的任一節都可以單獨換給甲補,
    其餘幾節照常由乙上。跳過非一般課的節次(與 leaves.expand 展開連堂的規則一致)。
    """
    out = []
    for no in range(entry.period_no, entry.period_no + entry.span):
        p = av.entry_period(entry, no)
        if p is None or p.type == PeriodType.regular.value:
            out.append(no)
    return out


class SwapChecker:
    """針對一個受影響節次,檢查「乙能不能來」與「某一節能不能拿來換」。

    同一次搜尋會對很多組合反覆問同樣的問題(甲某天某節有沒有空),故查詢結果快取在實例上。
    """

    def __init__(self, db: Session, affected: AffectedPeriod, av: Availability) -> None:
        self.db = db
        self.affected = affected
        self.av = av
        self.absent: Teacher = affected.leave_request.teacher
        self.semester = db.get(Semester, affected.semester_id)
        self._taken: set[tuple[int, date, int]] | None = None

    def partner_blocker(self, partner: Teacher) -> str | None:
        """乙在甲請假那節能不能來上課(自己有課、也請假、已被安排代別班都不行)。"""
        a = self.affected
        conflict = self.av.conflict_for(partner.id, a.date, self.av.slot_of(a))
        if conflict is None:
            return None
        return f"{partner.name} {a.date} {a.period_name} {conflict.detail}"

    def _taken_slots(self) -> set[tuple[int, date, int]]:
        """已經被其他有效調課拿去換的 (乙的格位, 日期, 節次)。同一節課不能換給兩個人補。"""
        if self._taken is None:
            rows = self.db.execute(
                select(Substitution.swap_entry_id, Substitution.swap_date,
                       Substitution.swap_period_no)
                .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
                .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
                .where(
                    Substitution.semester_id == self.affected.semester_id,
                    Substitution.type == SubstitutionType.swap.value,
                    Substitution.affected_period_id != self.affected.id,
                    AffectedPeriod.status != AffectedStatus.cancelled.value,
                    LeaveRequest.status == LeaveStatus.registered.value,
                )
            ).all()
            self._taken = {
                (e, d, n) for e, d, n in rows if e is not None and d is not None and n is not None
            }
        return self._taken

    def option_blocker(
        self, partner: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """乙的 `entry` 格位中第 `period_no` 節,在 `when` 這天能不能改由甲來補。"""
        pname = _period_label(self.av, entry, period_no)
        slot = self.av.entry_slot(entry, period_no)
        sem = self.semester
        if sem is not None and (
            (sem.start_date and when < sem.start_date) or (sem.end_date and when > sem.end_date)
        ):
            return f"{when} 不在學期期間內"
        if clock.is_past_slot(when, slot.end):
            return f"{when} {pname} 已經上過,無法補課"
        if self.av.is_on_leave(partner.id, when, slot):
            return f"{partner.name} {when} {pname} 也請假,這節課本身就需要安排,不能拿來對調"
        if (entry.id, when, period_no) in self._taken_slots():
            return f"{partner.name} {when} {pname} 這節已經和別的老師調課了"
        conflict = self.av.conflict_for(self.absent.id, when, slot)
        if conflict is not None:
            return f"{self.absent.name} 無法在 {when} {pname} 補課:{conflict.detail}"
        return None


# ── 搜尋 ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SwapOption:
    entry_id: int
    date: date
    weekday: int
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    same_class: bool  # 與請假那節是同一班(真正的「同班互調」,學生只是兩科前後對換)
    in_block: bool    # 是連堂中的一節(只換這一節,其餘照常由乙上)


@dataclass
class SwapPartner:
    teacher_id: int
    teacher_name: str
    teaches_same_class: bool
    blocked_reason: str = ""  # 非空 = 乙本身在請假那節就來不了,options 必為空
    options: list[SwapOption] = field(default_factory=list)


@dataclass
class SwapSearch:
    affected_period_id: int
    date_from: date
    date_to: date
    partners: list[SwapPartner] = field(default_factory=list)


def search_window(on: date) -> tuple[date, date]:
    """請假那天所在週的週一,到下週日。組長實務上是「當週互調,或和下週調」。"""
    monday = on - timedelta(days=on.isoweekday() - 1)
    return monday, monday + timedelta(days=13)


def _class_ids_of(db: Session, assignment_id: int | None) -> set[int]:
    if assignment_id is None:
        return set()
    a = db.get(CourseAssignment, assignment_id)
    return {m.class_unit_id for m in a.scheduling_unit.members} if a else set()


def _same_class_teacher_ids(
    db: Session, timetable_id: int, class_ids: set[int], exclude: int
) -> set[int]:
    """已發布課表中,也在這些班級上課的教師。"""
    if not class_ids:
        return set()
    rows = db.execute(
        select(AssignmentTeacher.teacher_id)
        .join(CourseAssignment, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .join(SchedulingUnitMember,
              SchedulingUnitMember.scheduling_unit_id == CourseAssignment.scheduling_unit_id)
        .join(ScheduleEntry, ScheduleEntry.course_assignment_id == CourseAssignment.id)
        .where(
            ScheduleEntry.timetable_id == timetable_id,
            SchedulingUnitMember.class_unit_id.in_(class_ids),
        )
    ).all()
    return {r[0] for r in rows} - {exclude}


def search(
    db: Session,
    affected: AffectedPeriod,
    *,
    teacher_id: int | None = None,
    availability: Availability | None = None,
) -> SwapSearch:
    """列出可對調的節次。

    `teacher_id` 為空時只找「也教這個班」的老師(最常見的同班互調);
    指定時只看那一位(組長心裡已經有人選)。
    """
    av = availability or Availability(db, affected.semester_id)
    date_from, date_to = search_window(affected.date)
    result = SwapSearch(affected_period_id=affected.id, date_from=date_from, date_to=date_to)
    if av.timetable is None:
        return result

    checker = SwapChecker(db, affected, av)
    class_ids = _class_ids_of(db, affected.course_assignment_id)
    same_class_ids = _same_class_teacher_ids(
        db, av.timetable.id, class_ids, exclude=checker.absent.id)

    if teacher_id is not None:
        ids = {teacher_id} - {checker.absent.id}
    else:
        ids = same_class_ids
    if not ids:
        return result
    partners = db.scalars(
        select(Teacher).where(
            Teacher.id.in_(ids),
            Teacher.semester_id == affected.semester_id,
            Teacher.is_active.is_(True),
        ).order_by(Teacher.name)
    ).all()

    dates = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    for partner in partners:
        sp = SwapPartner(
            teacher_id=partner.id, teacher_name=partner.name,
            teaches_same_class=partner.id in same_class_ids,
        )
        result.partners.append(sp)
        blocked = checker.partner_blocker(partner)
        if blocked is not None:
            sp.blocked_reason = blocked
            continue

        entries = db.scalars(
            select(ScheduleEntry)
            .join(AssignmentTeacher,
                  AssignmentTeacher.course_assignment_id == ScheduleEntry.course_assignment_id)
            .where(
                ScheduleEntry.timetable_id == av.timetable.id,
                AssignmentTeacher.teacher_id == partner.id,
            )
        ).unique().all()
        for entry in entries:
            a = db.get(CourseAssignment, entry.course_assignment_id)
            if a is None:
                continue
            entry_classes = {m.class_unit_id for m in a.scheduling_unit.members}
            class_names = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
            for when in dates:
                if when.isoweekday() != entry.weekday:
                    continue
                for no in block_periods(av, entry):
                    if when == affected.date and no == affected.period_no:
                        continue
                    if checker.option_blocker(partner, entry, when, no) is not None:
                        continue
                    sp.options.append(SwapOption(
                        entry_id=entry.id, date=when, weekday=entry.weekday,
                        period_no=no, period_name=_period_label(av, entry, no),
                        class_names=class_names,
                        subject_name=a.subject.name if a.subject else "",
                        same_class=bool(entry_classes & class_ids),
                        in_block=entry.span > 1,
                    ))
        sp.options.sort(key=lambda o: (not o.same_class, o.date, o.period_no))

    # 有得換的排前面;同班老師優先
    result.partners.sort(key=lambda p: (
        not p.options, not p.teaches_same_class, p.teacher_name))
    return result
