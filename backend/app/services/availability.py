"""特定日期的教師可用性(M4-2)。

**這是「週循環格」與「特定日期」的交界。** 課表只知道「李師週三第二節有課」;
但要判斷「11/11(週三)第二節李師能不能來代課」,週格不夠——那個週三他自己可能也
請假了,或已經被指派去代別班。這一層把三件事疊起來:

1. **週課表**:李師在該節次的牆鐘時間有沒有自己的課(D7:跨節次表以時間重疊判定)。
2. **當日請假**:李師那一天那個時段自己是不是也請假了。
3. **當日已接手**:李師是不是已經被指派代別班、或調課到那個時段。

M4-4 的今日看板、M4-2 的代課推薦都建立在這一層上。判斷一律用牆鐘時間區間,
不用 period_no——不同節次表的「第二節」時間不同(D7)。
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import Period
from app.models.substitution import Substitution
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services import period_tables as pt_service


@dataclass(frozen=True, slots=True)
class Interval:
    """某個上課時段的牆鐘區間。缺起訖時間時退化為 period_no(單表學校的正確值)。"""

    weekday: int
    period_no: int
    start: time | None
    end: time | None

    def overlaps(self, other: "Interval") -> bool:
        if self.weekday != other.weekday:
            return False
        if self.start and self.end and other.start and other.end:
            return self.start < other.end and other.start < self.end
        # 任一方缺時間:退化為同節次號(單一節次表的學校天然如此)
        return self.period_no == other.period_no


@dataclass(frozen=True, slots=True)
class Conflict:
    """為什麼這位教師那個時段不能用。"""

    kind: str  # teaching / on_leave / already_covering
    detail: str


def _window_covers(slot: Interval, begin: time | None, finish: time | None) -> bool:
    """slot 是否落在請假時間窗 [begin, finish] 內(None = 該端點不限,即整天/半天開放端)。"""
    if begin is None and finish is None:
        return True  # 整天假
    if slot.start is None or slot.end is None:
        return True  # 節次缺時間時保守視為涵蓋(與 leaves 展開的保守策略一致)
    if finish is not None and slot.start >= finish:
        return False
    if begin is not None and slot.end <= begin:
        return False
    return True


def published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )


class Availability:
    """一個學期的可用性查詢器。批次撈好課表/請假/處置,供推薦引擎逐一比對。

    只建構一次、重複查詢:代課推薦要對全校教師逐一判斷同一個時段。
    """

    def __init__(self, db: Session, semester_id: int, timetable: Timetable | None = None) -> None:
        self.db = db
        self.semester_id = semester_id
        self.timetable = timetable or published_timetable(db, semester_id)
        self._teaching: dict[int, list[Interval]] | None = None
        self._table_periods: dict[int, dict[tuple[int, int], Period]] = {}

    # ── 週課表:每位教師的授課時段(牆鐘區間)──
    def _teaching_map(self) -> dict[int, list[Interval]]:
        if self._teaching is not None:
            return self._teaching
        result: dict[int, list[Interval]] = {}
        if self.timetable is None:
            self._teaching = result
            return result

        rows = self.db.execute(
            select(
                ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.span,
                CourseAssignment.id, AssignmentTeacher.teacher_id,
            )
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
            .where(ScheduleEntry.timetable_id == self.timetable.id)
        ).all()

        for weekday, period_no, span, a_id, teacher_id in rows:
            table_id = self._table_of_assignment(a_id)
            for k in range(span):
                p = self._period(table_id, weekday, period_no + k) if table_id else None
                result.setdefault(teacher_id, []).append(Interval(
                    weekday, period_no + k,
                    p.start_time if p else None, p.end_time if p else None,
                ))
        self._teaching = result
        return result

    def _table_of_assignment(self, assignment_id: int) -> int | None:
        a = self.db.get(CourseAssignment, assignment_id)
        if a is None or not a.scheduling_unit.members:
            return None
        table = pt_service.resolve_period_table(self.db, a.scheduling_unit.members[0].class_unit)
        return table.id if table else None

    def _period(self, table_id: int, weekday: int, period_no: int) -> Period | None:
        if table_id not in self._table_periods:
            rows = self.db.scalars(select(Period).where(Period.period_table_id == table_id))
            self._table_periods[table_id] = {(p.weekday, p.period_no): p for p in rows}
        return self._table_periods[table_id].get((weekday, period_no))

    # ── 當日請假:該教師自己那天那個時段是否也請假 ──
    def _on_leave(self, teacher_id: int, when: date, slot: Interval) -> bool:
        """該教師在 when 這天的 slot 時段是否請假。

        **必須讀假單本身的日期/時間窗,不是展開的 affected_period。**
        後者只在「有課的節次」才存在——一位老師請整天假、而該節恰好是他的空堂時,
        affected_period 不會涵蓋那一格,但他人確實不在,不能被找來代課。
        """
        rows = self.db.execute(
            select(LeaveRequest.start_date, LeaveRequest.start_time,
                   LeaveRequest.end_date, LeaveRequest.end_time)
            .where(
                LeaveRequest.teacher_id == teacher_id,
                LeaveRequest.status == LeaveStatus.registered.value,
                LeaveRequest.start_date <= when,
                LeaveRequest.end_date >= when,
            )
        ).all()
        for start_date, start_time, end_date, end_time in rows:
            # 只有假期頭尾兩天受時間限制,中間整天(與 leaves.expand 同一套語意)
            begin = start_time if when == start_date else None
            finish = end_time if when == end_date else None
            if _window_covers(slot, begin, finish):
                return True
        return False

    # ── 當日已接手:已被指派代別班/調課到那個時段 ──
    def _already_covering(self, teacher_id: int, when: date, slot: Interval) -> Interval | None:
        # (a) 身為其他受影響節次的代課/接手者
        rows = self.db.execute(
            select(AffectedPeriod.weekday, AffectedPeriod.period_no,
                   AffectedPeriod.start_time, AffectedPeriod.end_time)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                AffectedPeriod.handler_teacher_id == teacher_id,
                AffectedPeriod.status == AffectedStatus.resolved.value,
                LeaveRequest.status == LeaveStatus.registered.value,
                AffectedPeriod.date == when,
            )
        ).all()
        for weekday, period_no, start, end in rows:
            other = Interval(weekday, period_no, start, end)
            if slot.overlaps(other):
                return other
        # (b) 身為調課的補課者(swap 的甲方,補在 swap_date)。
        # **補課方是該筆調課「請假的當事人」**,不是 handler(乙);必須以
        # AffectedPeriod→LeaveRequest.teacher_id 比對,否則會把全校在該時段都誤判為已佔用。
        swaps = self.db.execute(
            select(Substitution.swap_period_no)
            .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                Substitution.swap_date == when,
                LeaveRequest.teacher_id == teacher_id,
                LeaveRequest.status == LeaveStatus.registered.value,
                AffectedPeriod.status != AffectedStatus.cancelled.value,
            )
        ).all()
        for (swap_period_no,) in swaps:
            if swap_period_no == slot.period_no:  # 調課補課以節次號記錄
                return Interval(slot.weekday, swap_period_no, None, None)
        return None

    # ── 對外:某教師某時段能不能用 ──
    def slot_of(self, affected: AffectedPeriod) -> Interval:
        return Interval(affected.weekday, affected.period_no,
                        affected.start_time, affected.end_time)

    def teaching_at(self, teacher_id: int, slot: Interval) -> Interval | None:
        for iv in self._teaching_map().get(teacher_id, []):
            if iv.overlaps(slot):
                return iv
        return None

    def conflict_for(self, teacher_id: int, when: date, slot: Interval) -> Conflict | None:
        """該教師在 when 這一天的 slot 時段,有沒有不能來的理由(回第一個)。"""
        if self.teaching_at(teacher_id, slot) is not None:
            return Conflict("teaching", "該時段有自己的課")
        if self._on_leave(teacher_id, when, slot):
            return Conflict("on_leave", "當天也請假")
        if self._already_covering(teacher_id, when, slot) is not None:
            return Conflict("already_covering", "已被安排代其他課")
        return None

    def is_free(self, teacher_id: int, when: date, slot: Interval) -> bool:
        return self.conflict_for(teacher_id, when, slot) is None

    def teaches_on(self, teacher_id: int, weekday: int) -> bool:
        """該教師在某星期是否有課——用來判斷『當天已在校』(免多跑一趟)。"""
        return any(iv.weekday == weekday for iv in self._teaching_map().get(teacher_id, []))
