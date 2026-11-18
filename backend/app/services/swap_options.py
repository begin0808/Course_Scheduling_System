"""調課:可對調節次的搜尋與逐項檢查(v1.2.1)。

調課的語意見 `models/substitution.py`:甲請假那節由乙來上,甲之後補乙的一節。
後端 M4-2 只會「驗」組長選好的組合;但組長不會自己去翻乙哪一節、哪一天能換——
這裡替他列出請假那週起**數週內**(預設兩週,最多四週)所有真的換得成的組合;
換不了的也列出來並寫原因(v1.4.12),組長才看得懂為什麼某一節不能選。

**列出的與送出時驗的必須是同一套規則**,否則清單上點得到、按下去卻被拒絕。
所以逐項檢查集中在 `SwapChecker`,`substitutions._validate_swap` 也呼叫它。

**三角調課**(v1.4.20,`triangle_search`):兩人互調湊不出來時,同一班三位老師輪流換課——
乙來上甲請假那節、丙來上乙原本的一節、甲回來上丙原本的一節。只限同一個班的一般課
(一位老師上的課;跑班、單雙週組、協同教學不列),找的範圍與互調相同。

**指定老師**(v1.4.21,組長回報「三角調課的清單裡找不到某位老師」):清單只列換得成的組合,
湊不出來時組長看不出卡在哪裡;指定一位老師就逐節寫出他在每個位置為什麼不行
(`TeacherCheck`),他的組合也不受 `MAX_TRIANGLES` 截斷。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment, SchedulingUnitMember
from app.models.basedata import Teacher
from app.models.leave import (
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
)
from app.models.period import PeriodType
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import leaves
from app.services import suspensions as suspension_service
from app.services.availability import Availability, Interval


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
        self._in_leave: dict[tuple[int, date], dict[int, str]] = {}
        self._labels: dict[int, str] = {}
        # 停課的那一節不上課,不能拿來補課(v1.4.19)
        self.calendar = suspension_service.Calendar(
            db, affected.semester_id, date.min, date.max)
        # 補登已經上過的調課(v1.4.10,組長回報:事後補登,留紀錄查老師多常換課):
        # 兩邊都已經上完了,補課那節也可以是過去的。只限「調課(未請假)」——
        # 請假的節次過去了只能補登代課(`substitutions.assign`)。
        self.backfill = (
            affected.leave_request.leave_type == LeaveType.swap_only.value
            and affected.status == AffectedStatus.pending.value
            and clock.is_past_slot(affected.date, affected.end_time)
        )

    def partner_blocker(self, partner: Teacher) -> str | None:
        """乙在甲請假那節能不能來上課(自己有課、也請假、已被安排代別班都不行)。"""
        a = self.affected
        conflict = self.av.conflict_for(partner.id, a.date, self.av.slot_of(a))
        if conflict is None:
            return None
        return f"{partner.name} {a.date} {a.period_name} {conflict.detail}"

    def _taken_slots(self) -> set[tuple[int, date, int]]:
        """已經被其他有效調課拿去換的 (乙的格位, 日期, 節次)。同一節課不能換給兩個人補。

        三角調課(v1.4.20)換掉的兩格(乙那節、丙那節)都算,三角調的節次不能再調。
        """
        if self._taken is None:
            rows = self.db.execute(
                select(Substitution.swap_entry_id, Substitution.swap_date,
                       Substitution.swap_period_no, Substitution.tri_entry_id,
                       Substitution.tri_date, Substitution.tri_period_no)
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
                (e, d, n) for r in rows for e, d, n in (r[:3], r[3:])
                if e is not None and d is not None and n is not None
            }
        return self._taken

    def in_leave(self, teacher: Teacher, when: date, period_no: int) -> str:
        """這位老師這一節已經在別張有效的假單或「調課(未請假)」裡 → 那張的假別名稱。

        那一節已經交給別人處理了,不能再拿來對調(v1.4.20)。請假的本人不算
        (他那幾節就是這一筆要處理的)。
        """
        if teacher.id == self.absent.id:
            return ""
        key = (teacher.id, when)
        if key not in self._in_leave:
            self._in_leave[key] = leaves.taken_periods(self.db, teacher.id, when)
        return self._in_leave[key].get(period_no, "")

    def option_blocker(
        self, partner: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """乙的 `entry` 格位中第 `period_no` 節,在 `when` 這天能不能改由甲來補。"""
        pname = _period_label(self.av, entry, period_no)
        if self._out_of_term(when):
            return f"{when} 不在學期期間內"
        if self.out_of_reach(entry, when, period_no):
            return f"{when} {pname} 已經上過,無法補課"
        reason = self.reason(partner, entry, when, period_no)
        return f"{when} {pname} {reason}" if reason else None

    def out_of_reach(self, entry: ScheduleEntry, when: date, period_no: int) -> bool:
        """不在學期內、或已經上過(補登除外)——清單上連灰色都不列,列了也沒意義。"""
        if self._out_of_term(when):
            return True
        slot = self.av.entry_slot(entry, period_no)
        return clock.is_past_slot(when, slot.end) and not self.backfill

    def _out_of_term(self, when: date) -> bool:
        sem = self.semester
        return sem is not None and bool(
            (sem.start_date and when < sem.start_date) or (sem.end_date and when > sem.end_date)
        )

    def reason(
        self, partner: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """換不了的原因(不含日期、節次——清單上那一格已經寫了)。換得了回 None。

        v1.4.12:組長兩度回報「調課清單抓不到某一節」,兩次系統都對,只是看不出原因
        (補課老師那節自己有課;請假時段蓋住那一節)。所以換不了的也列出來、寫原因。
        """
        off = self.calendar.for_entry(entry, when, period_no)
        if off is not None:
            return f"這節{suspension_service.label(off)},不能補課"
        slot = self.av.entry_slot(entry, period_no)
        if self.av.is_on_leave(partner.id, when, slot):
            return f"{partner.name}這節也請假,這節課本身就需要安排,不能拿來對調"
        if (entry.id, when, period_no) in self._taken_slots():
            return f"{partner.name}這節已經和別的老師調課了"
        taken = self.in_leave(partner, when, period_no)
        if taken:
            return f"{partner.name}這節已經在「{taken}」裡,不能拿來對調"
        absent = self.absent.name
        released = self._released(when)
        if self.av.is_on_leave(self.absent.id, when, slot):
            return f"{absent}這個時段請假,不能補課"
        hit = self.av.lesson_at(self.absent.id, slot, when, released)
        if hit is not None:
            iv, assignment_id = hit
            what = self._lesson_label(assignment_id)
            if iv.period_no != period_no and iv.start and iv.end:
                # 兩班節次表不同,重疊的是另一個節次號:寫出時間才看得懂
                what += f" {iv.start:%H:%M}~{iv.end:%H:%M}"
            return f"{absent}這節自己有課({what})"
        conflict = self.av.conflict_for(self.absent.id, when, slot, released)
        if conflict is not None:
            return f"{absent}{conflict.detail}"
        return None

    def mid_reason(
        self, owner: Teacher, third: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """三角調課的中間那一節:乙(`owner`)原本的這一節,能不能改由丙(`third`)來上。"""
        return (self.mid_base_reason(owner, entry, when, period_no)
                or self.third_reason(third, entry, when, period_no))

    def mid_base_reason(
        self, owner: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """中間那一節本身能不能讓出來(與來上的是誰無關)。"""
        off = self.calendar.for_entry(entry, when, period_no)
        if off is not None:
            return f"這節{suspension_service.label(off)},不能調課"
        slot = self.av.entry_slot(entry, period_no)
        if self.av.is_on_leave(owner.id, when, slot):
            return f"{owner.name}這節也請假,這節課本身就需要安排,不能拿來對調"
        if (entry.id, when, period_no) in self._taken_slots():
            return f"{owner.name}這節已經和別的老師調課了"
        taken = self.in_leave(owner, when, period_no)
        if taken:
            return f"{owner.name}這節已經在「{taken}」裡,不能拿來對調"
        return None

    def third_reason(
        self, third: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """丙這一節能不能來上課(自己有課、請假、已被安排代課都不行)。"""
        return self.busy(third, when, self.av.entry_slot(entry, period_no))

    def busy(self, teacher: Teacher, when: date, slot: Interval) -> str | None:
        """這位老師這個時段能不能來上課;不能時寫原因(「林師這節自己有課(401 體育)」)。"""
        hit = self.av.lesson_at(teacher.id, slot, when)
        if hit is not None:
            return f"{teacher.name}這節自己有課({self._lesson_label(hit[1])})"
        conflict = self.av.conflict_for(teacher.id, when, slot)
        if conflict is not None:
            return f"{teacher.name}{conflict.detail}"
        return None

    def _lesson_label(self, assignment_id: int) -> str:
        """「702 自然」:配課的班級與科目。"""
        if assignment_id not in self._labels:
            a = self.db.get(CourseAssignment, assignment_id)
            if a is None:
                self._labels[assignment_id] = ""
            else:
                classes = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
                subject = a.subject.name if a.subject else ""
                self._labels[assignment_id] = f"{classes} {subject}".strip()
        return self._labels[assignment_id]

    def _released(self, when: date) -> list[Interval]:
        """甲在 `when` 這天、同一筆「調課(未請假)」裡的節次(v1.4.9,組長回報)。

        學校活動讓 402、502 兩班的第七、八節同時對調,洪師兩節都要換:
        502 那筆要他第七節補課,卻被他第七節的 402 擋住;402 那筆又被第八節的 502 擋住。
        這幾節既然都列在同一筆調課裡、都會交給別人上,就不算他那節有課。
        只限沒請假的調課:真的請假時,假單時段內他本來就不能補課(請假檢查會擋)。
        """
        leave = self.affected.leave_request
        if leave.leave_type != LeaveType.swap_only.value:
            return []
        return [
            self.av.slot_of(ap) for ap in leave.affected_periods
            if ap.date == when and ap.status != AffectedStatus.cancelled.value
        ]


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
    blocked_reason: str = ""  # 非空 = 換不了,灰色列出原因(v1.4.12)


@dataclass
class SwapPartner:
    teacher_id: int
    teacher_name: str
    teaches_same_class: bool
    blocked_reason: str = ""  # 非空 = 乙本身在請假那節就來不了,options 必為空
    options: list[SwapOption] = field(default_factory=list)
    # 換不了的節次與原因(v1.4.12);已上過、不在學期內的不列
    blocked: list[SwapOption] = field(default_factory=list)


@dataclass
class SwapSearch:
    affected_period_id: int
    date_from: date
    date_to: date
    partners: list[SwapPartner] = field(default_factory=list)


DEFAULT_WEEKS = 2
MAX_WEEKS = 4


def search_window(
    on: date, weeks: int = DEFAULT_WEEKS, start: date | None = None
) -> tuple[date, date]:
    """請假那天所在週的週一,往後共 `weeks` 週(到最後一週的週日)。

    預設兩週(當週互調或和下週調);使用學校實務上常有隔週、甚至「本週與隔三週」對調,
    故最多開到四週。範圍再大,清單會長到組長找不到要的那一節。

    `start`(v1.4.12,組長回報):老師一月請假、想十一月就先補課,
    改從 `start` 所在的那週開始找。送出時的檢查本來就不限日期在請假之後。
    """
    weeks = max(1, min(weeks, MAX_WEEKS))
    base = start or on
    monday = base - timedelta(days=base.isoweekday() - 1)
    return monday, monday + timedelta(days=7 * weeks - 1)


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
    weeks: int = DEFAULT_WEEKS,
    start: date | None = None,
    availability: Availability | None = None,
) -> SwapSearch:
    """列出可對調的節次。

    `teacher_id` 為空時只找「也教這個班」的老師(最常見的同班互調);
    指定時只看那一位(組長心裡已經有人選)。
    """
    av = availability or Availability(db, affected.semester_id)
    date_from, date_to = search_window(affected.date, weeks, start)
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
                if when.isoweekday() != entry.weekday or not av.entry_runs_on(entry, when):
                    continue
                for no in block_periods(av, entry):
                    if when == affected.date and no == affected.period_no:
                        continue
                    if checker.out_of_reach(entry, when, no):
                        continue
                    reason = checker.reason(partner, entry, when, no)
                    (sp.blocked if reason else sp.options).append(SwapOption(
                        entry_id=entry.id, date=when, weekday=entry.weekday,
                        period_no=no, period_name=_period_label(av, entry, no),
                        class_names=class_names,
                        subject_name=a.subject.name if a.subject else "",
                        same_class=bool(entry_classes & class_ids),
                        in_block=entry.span > 1,
                        blocked_reason=reason or "",
                    ))
        sp.options.sort(key=lambda o: (not o.same_class, o.date, o.period_no))
        sp.blocked.sort(key=lambda o: (not o.same_class, o.date, o.period_no))

    # 有得換的排前面;同班老師優先
    result.partners.sort(key=lambda p: (
        not p.options, not p.teaches_same_class, p.teacher_name))
    return result


# ── 三角調課(v1.4.20)────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Lesson:
    """這一班某一天某一節的一般課(一位老師上),三角調課的候選格。"""

    entry_id: int
    date: date
    weekday: int
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    in_block: bool
    teacher_id: int
    teacher_name: str


@dataclass(frozen=True, slots=True)
class TriangleOption:
    """一組三角調課:乙來上請假那節;丙來上乙的 `mid`;甲回來上丙的 `makeup`。"""

    partner_id: int
    partner_name: str
    mid: Lesson
    third_id: int
    third_name: str
    makeup: Lesson


@dataclass(frozen=True, slots=True)
class ClassTeacher:
    """這一班(請假老師以外)有一般課的老師:「指定老師」的選單。"""

    teacher_id: int
    teacher_name: str


@dataclass
class TeacherCheck:
    """指定一位老師(v1.4.21):他能湊成幾組,其餘的節次為什麼不行。"""

    teacher_id: int
    teacher_name: str
    found: int = 0
    note: str = ""  # 非空 = 根本沒有這一班的課
    # 當 ①:來上請假那一節(要讓出自己的一節給別人上)
    as_partner: list[str] = field(default_factory=list)
    # 當 ②:來上別人讓出的一節,請假老師回來上他的課
    as_third: list[str] = field(default_factory=list)


@dataclass
class TriangleSearch:
    affected_period_id: int
    date_from: date
    date_to: date
    unavailable: str = ""   # 非空 = 這一節不能三角調課的原因(跑班、協同教學…)
    total: int = 0          # 一共幾組(清單只回前 MAX_TRIANGLES 組)
    options: list[TriangleOption] = field(default_factory=list)
    teachers: list[ClassTeacher] = field(default_factory=list)
    check: TeacherCheck | None = None


MAX_TRIANGLES = 200
_WEEKDAY_TEXT = "一二三四五六日"


def _when(day: date, period_name: str) -> str:
    """「12/16(週三) 第四節」。"""
    return f"{day.month}/{day.day}(週{_WEEKDAY_TEXT[day.isoweekday() - 1]}) {period_name}".strip()


def _lesson_text(x: Lesson) -> str:
    return f"{_when(x.date, x.period_name)} {x.subject_name}".strip()


def triangle_unit(db: Session, affected: AffectedPeriod) -> tuple[int | None, str]:
    """請假那節能不能三角調課:回 (排課單位 id, 不能的原因)。

    只限一個班、一位老師上的一般課——跑班、單雙週組、協同教學一節裡有好幾門課或好幾位老師,
    三個人輪流換,學生那一節到底上什麼會說不清楚。
    """
    a = (db.get(CourseAssignment, affected.course_assignment_id)
         if affected.course_assignment_id else None)
    if a is None:
        return None, "找不到這一節的配課"
    if a.scheduling_unit.unit_type != "single":
        return None, "跑班或單雙週組的課不能三角調課,請用互調或代課"
    if len(a.teachers) != 1:
        return None, "協同教學的課不能三角調課,請用互調或代課"
    return a.scheduling_unit_id, ""


def class_lessons(
    db: Session, av: Availability, checker: SwapChecker, unit_id: int, dates: list[date],
) -> list[Lesson]:
    """這個班在這段期間、請假老師以外的每一節一般課(還沒上過的)。"""
    assert av.timetable is not None
    affected = checker.affected
    out: list[Lesson] = []
    entries = db.scalars(
        select(ScheduleEntry)
        .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
        .where(ScheduleEntry.timetable_id == av.timetable.id,
               CourseAssignment.scheduling_unit_id == unit_id)
    ).all()
    for entry in entries:
        a = entry.assignment
        if len(a.teachers) != 1:
            continue
        teacher = a.teachers[0].teacher
        if teacher.id == checker.absent.id or not teacher.is_active:
            continue
        class_names = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
        for when in dates:
            if when.isoweekday() != entry.weekday or not av.entry_runs_on(entry, when):
                continue
            for no in block_periods(av, entry):
                if when == affected.date and no == affected.period_no:
                    continue
                if checker.out_of_reach(entry, when, no):
                    continue
                out.append(Lesson(
                    entry_id=entry.id, date=when, weekday=entry.weekday, period_no=no,
                    period_name=_period_label(av, entry, no), class_names=class_names,
                    subject_name=a.subject.name if a.subject else "",
                    in_block=entry.span > 1, teacher_id=teacher.id, teacher_name=teacher.name,
                ))
    return out


def triangle_search(
    db: Session,
    affected: AffectedPeriod,
    *,
    weeks: int = DEFAULT_WEEKS,
    start: date | None = None,
    availability: Availability | None = None,
    teacher_id: int | None = None,
) -> TriangleSearch:
    """列出可行的三人組合:乙在甲那節有空、丙在乙那節有空、甲在丙那節有空。

    每一格的檢查與互調同一套(`SwapChecker`):停課、請假、已經拿去調課、自己有課、
    已被安排代課都不行。依兩節裡較晚的那天排序(越早換完越好)。
    `teacher_id`:只列有這位老師(當 ① 或 ②)的組合,並寫出他其餘節次為什麼不行。
    """
    av = availability or Availability(db, affected.semester_id)
    date_from, date_to = search_window(affected.date, weeks, start)
    result = TriangleSearch(affected_period_id=affected.id, date_from=date_from, date_to=date_to)
    if av.timetable is None:
        result.unavailable = "此學期尚無已發布的課表"
        return result
    unit_id, why = triangle_unit(db, affected)
    if unit_id is None:
        result.unavailable = why
        return result

    checker = SwapChecker(db, affected, av)
    dates = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    lessons = class_lessons(db, av, checker, unit_id, dates)
    teachers = {t.id: t for t in db.scalars(
        select(Teacher).where(Teacher.id.in_({x.teacher_id for x in lessons} or [0])))}
    entries = {e.id: e for e in db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.id.in_({x.entry_id for x in lessons} or [0])))}

    result.teachers = sorted(
        (ClassTeacher(teacher_id=t.id, teacher_name=t.name) for t in teachers.values()),
        key=lambda t: t.teacher_name)
    partner_ok = {tid: checker.partner_blocker(t) is None for tid, t in teachers.items()}
    # 甲能不能回來上這一節(丙的課)
    makeups: dict[int, list[Lesson]] = {}
    for x in lessons:
        if checker.reason(teachers[x.teacher_id], entries[x.entry_id], x.date,
                          x.period_no) is None:
            makeups.setdefault(x.teacher_id, []).append(x)

    found: list[TriangleOption] = []
    for mid in lessons:
        if not partner_ok[mid.teacher_id]:
            continue
        owner, entry = teachers[mid.teacher_id], entries[mid.entry_id]
        if checker.mid_base_reason(owner, entry, mid.date, mid.period_no) is not None:
            continue
        for third_id, options in makeups.items():
            if third_id == mid.teacher_id:
                continue
            third = teachers[third_id]
            if checker.third_reason(third, entry, mid.date, mid.period_no) is not None:
                continue
            for z in options:
                found.append(TriangleOption(
                    partner_id=owner.id, partner_name=owner.name, mid=mid,
                    third_id=third.id, third_name=third.name, makeup=z))

    if teacher_id is not None:
        found = [o for o in found if teacher_id in (o.partner_id, o.third_id)]
        result.check = _teacher_check(
            db, checker, teacher_id, lessons, teachers, entries, partner_ok, makeups, len(found))
    found.sort(key=lambda o: (max(o.mid.date, o.makeup.date), o.mid.date, o.mid.period_no,
                              o.makeup.date, o.makeup.period_no, o.partner_name, o.third_name))
    result.total = len(found)
    result.options = found[:MAX_TRIANGLES]
    return result


def _teacher_check(
    db: Session,
    checker: SwapChecker,
    teacher_id: int,
    lessons: list[Lesson],
    teachers: dict[int, Teacher],
    entries: dict[int, ScheduleEntry],
    partner_ok: dict[int, bool],
    makeups: dict[int, list[Lesson]],
    found: int,
) -> TeacherCheck:
    """這位老師在三角調課的兩個位置,每一節為什麼湊不成(v1.4.21)。

    ①:他來上請假那一節,讓出自己的一節給第三位老師上;
    ②:他來上別人讓出的一節,請假老師回來上他的一節。
    """
    absent = checker.absent.name
    t = teachers.get(teacher_id) or db.get(Teacher, teacher_id)
    chk = TeacherCheck(teacher_id=teacher_id, teacher_name=t.name if t else "", found=found)
    mine = [x for x in lessons if x.teacher_id == teacher_id]
    if t is None or not mine:
        chk.note = (f"{chk.teacher_name}在這段期間沒有這一班的課(或都已經上過);"
                    "三角調課只找同一班的老師,可以改用互調或代課")
        return chk

    a = checker.affected
    blocker = checker.busy(t, a.date, checker.av.slot_of(a))
    if blocker:
        chk.as_partner.append(f"不能來上請假那一節 {_when(a.date, a.period_name)}:{blocker}")
    else:
        others = [teachers[tid] for tid in makeups if tid != teacher_id]
        for x in mine:
            entry = entries[x.entry_id]
            why = checker.mid_base_reason(t, entry, x.date, x.period_no)
            if why is None:
                if any(checker.third_reason(o, entry, x.date, x.period_no) is None
                       for o in others):
                    continue
                why = (f"{absent}能回來上課的老師({'、'.join(o.name for o in others)})這節都沒空"
                       if others else f"{absent}沒辦法回來上這一班其他老師的任何一節")
            chk.as_partner.append(f"讓出 {_lesson_text(x)}:{why}")

    usable = []
    for x in mine:
        why = checker.reason(t, entries[x.entry_id], x.date, x.period_no)
        if why:
            chk.as_third.append(f"{absent}回來上{t.name}的 {_lesson_text(x)}:{why}")
        else:
            usable.append(x)
    if usable:
        mids = [m for m in lessons
                if m.teacher_id != teacher_id and partner_ok[m.teacher_id]
                and checker.mid_base_reason(teachers[m.teacher_id], entries[m.entry_id],
                                            m.date, m.period_no) is None]
        if not mids:
            chk.as_third.append(f"{absent}可以回來上{t.name}的課,但其他老師都沒辦法來上請假那一節"
                                "(或讓不出自己的課)")
        for m in mids:
            why = checker.third_reason(t, entries[m.entry_id], m.date, m.period_no)
            if why:
                chk.as_third.append(f"來上{m.teacher_name}的 {_lesson_text(m)}:{why}")
    return chk
