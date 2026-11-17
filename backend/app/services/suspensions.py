"""停課日的判斷(v1.4.19)。資料表見 `app.models.suspension`。

**一門課什麼時候算停課?** 這門課的「每一個班」在那一節都停課。跑班、合班的課只要還有
一個班照常上課,老師就還是要去上——例如只有 801 去戶外教學,801、802 合上的體育照常。

「第幾節」只數一般課,依每一班自己的節次表換算(國中小兩部作息不同也各自對得上);
早自習、午休這類時段只有「整天停課」才算在內。

本模組只讀;寫入在 `app.api.suspensions`。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    HomeroomCover,
    LeaveRequest,
    LeaveStatus,
)
from app.models.period import Period, PeriodType
from app.models.substitution import Substitution, SubstitutionType
from app.models.suspension import ClassSuspension
from app.models.timetable import ScheduleEntry
from app.services import period_tables as pt_service


def label(s: ClassSuspension) -> str:
    """「停課(校慶補假)」;沒寫說明就只寫「停課」。"""
    return f"停課({s.reason})" if s.reason else "停課"


def period_text(s: ClassSuspension) -> str:
    """「整天」「第 5 節」「第 5~7 節」。"""
    if s.all_day:
        return "整天"
    lo, hi = s.from_ordinal or 1, s.to_ordinal or s.from_ordinal or 1
    return f"第 {lo} 節" if lo == hi else f"第 {lo}~{hi} 節"


def target_text(s: ClassSuspension, all_classes: list[ClassUnit]) -> str:
    """「全校」「七年級」「七年級、801」:整個年級都選了就寫年級,其餘寫班名。

    年級依學制分開算(國中小:國小一年級與國中一年級是不同的年級)。
    """
    if s.whole_school:
        return "全校"
    chosen = {c.id for c in s.classes}
    grades: dict[tuple[str, int], list[ClassUnit]] = {}
    for c in all_classes:
        grades.setdefault((c.track, c.grade), []).append(c)
    multi_track = len({t for t, _ in grades}) > 1
    parts: list[str] = []
    for (track, grade), members in sorted(grades.items(), key=lambda x: (x[0][1], x[0][0])):
        picked = [c for c in members if c.id in chosen]
        if not picked:
            continue
        if len(picked) == len(members):
            parts.append(f"{_track_cn(track) if multi_track else ''}{_grade_cn(grade)}年級")
        else:
            parts.extend(c.name for c in picked)
    return "、".join(parts) or "(沒有班級)"


# 與前端 TRACK_LABELS 相同
_TRACK_CN = {
    "elementary": "國小", "junior_high": "國中", "senior_high": "普通型高中",
    "comprehensive": "綜合型高中", "vocational": "技術型高中",
}


def _track_cn(track: str) -> str:
    return _TRACK_CN.get(track, "")


def _grade_cn(grade: int) -> str:
    digits = "零一二三四五六七八九十"
    return digits[grade] if 0 <= grade <= 10 else str(grade)


@dataclass(frozen=True, slots=True)
class Conflict:
    """停課時段裡已經安排好的調代課:要組長自己決定撤回或改成「不處理」。"""

    date: date
    text: str


class Calendar:
    """一段期間的停課設定;依班級、日期、節次查詢。只建構一次、重複查詢。"""

    def __init__(
        self, db: Session, semester_id: int, start: date, end: date,
        rows: list[ClassSuspension] | None = None,
    ) -> None:
        self.db = db
        self.rows = rows if rows is not None else list(db.scalars(
            select(ClassSuspension).where(
                ClassSuspension.semester_id == semester_id,
                ClassSuspension.start_date <= end,
                ClassSuspension.end_date >= start,
            ).order_by(ClassSuspension.id)
        ))
        self._class_ids = {s.id: {c.id for c in s.classes} for s in self.rows}
        self._table_of: dict[int, int | None] = {}
        self._ordinals: dict[tuple[int, int], dict[int, int]] = {}

    def __bool__(self) -> bool:
        return bool(self.rows)

    def _ordinal(self, class_id: int, weekday: int, period_no: int) -> int | None:
        """這一班節次表裡,這一節是第幾節(只數一般課);不是一般課回 None。"""
        if class_id not in self._table_of:
            klass = self.db.get(ClassUnit, class_id)
            table = pt_service.resolve_period_table(self.db, klass) if klass else None
            self._table_of[class_id] = table.id if table else None
        table_id = self._table_of[class_id]
        if table_id is None:
            return period_no          # 沒有節次表:保守當作節次號就是第幾節
        key = (table_id, weekday)
        if key not in self._ordinals:
            regular = self.db.scalars(
                select(Period.period_no).where(
                    Period.period_table_id == table_id, Period.weekday == weekday,
                    Period.type == PeriodType.regular.value,
                ).order_by(Period.period_no)
            ).all()
            self._ordinals[key] = {no: i for i, no in enumerate(regular, start=1)}
        return self._ordinals[key].get(period_no)

    def _applies(self, s: ClassSuspension, class_id: int, day: date) -> bool:
        return (s.start_date <= day <= s.end_date
                and (s.whole_school or class_id in self._class_ids[s.id]))

    def for_class(self, class_id: int, day: date, period_no: int) -> ClassSuspension | None:
        """這一班這一天的這一節停課嗎?停課就回那一筆。"""
        for s in self.rows:
            if not self._applies(s, class_id, day):
                continue
            if s.all_day:
                return s
            ordinal = self._ordinal(class_id, day.isoweekday(), period_no)
            lo = s.from_ordinal or 1
            hi = s.to_ordinal or lo
            if ordinal is not None and lo <= ordinal <= hi:
                return s
        return None

    def for_classes(
        self, class_ids: Iterable[int], day: date, period_no: int,
    ) -> ClassSuspension | None:
        """每一個班都停課才算(合班、跑班還有一班要上,老師就要去)。"""
        if not self.rows:
            return None
        hits = [self.for_class(c, day, period_no) for c in class_ids]
        return hits[0] if hits and all(hits) else None

    def for_assignment(
        self, assignment: CourseAssignment | None, day: date, period_no: int,
    ) -> ClassSuspension | None:
        if assignment is None or not self.rows:
            return None
        return self.for_classes(
            [m.class_unit_id for m in assignment.scheduling_unit.members], day, period_no)

    def for_entry(self, entry: ScheduleEntry, day: date, period_no: int) -> ClassSuspension | None:
        return self.for_assignment(entry.assignment, day, period_no) if self.rows else None

    def all_day_for_class(self, class_id: int, day: date) -> ClassSuspension | None:
        """這一班這一天整天停課嗎?(代導以天為單位,整天停課才不必代導)"""
        return next((s for s in self.rows if s.all_day and self._applies(s, class_id, day)), None)


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def conflicts(db: Session, s: ClassSuspension) -> list[Conflict]:
    """這筆停課的時段裡,已經登記的請假節次、調課補課與代導。

    停課是事後才設的,之前安排的不自動改——可能已經通知了老師。列出來讓組長到
    「調代課處理」撤回,或改成「不處理(當天停課)」。
    """
    cal = Calendar(db, s.semester_id, s.start_date, s.end_date, rows=[s])
    out: list[Conflict] = []
    live = (
        LeaveRequest.status == LeaveStatus.registered.value,
        AffectedPeriod.status != AffectedStatus.cancelled.value,
        AffectedPeriod.semester_id == s.semester_id,
    )
    for ap in db.scalars(
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(AffectedPeriod.date >= s.start_date, AffectedPeriod.date <= s.end_date, *live)
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ):
        a = db.get(CourseAssignment, ap.course_assignment_id) if ap.course_assignment_id else None
        if cal.for_assignment(a, ap.date, ap.period_no) is None:
            continue
        who = ap.leave_request.teacher.name if ap.leave_request.teacher else ""
        out.append(Conflict(ap.date, (
            f"{_md(ap.date)} {ap.period_name} {ap.class_names} {ap.subject_name}:"
            f"{who} {LEAVE_TYPE_CN.get(ap.leave_request.leave_type, '請假')}")))

    for sub in db.scalars(
        select(Substitution)
        .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            Substitution.type == SubstitutionType.swap.value,
            Substitution.swap_date >= s.start_date, Substitution.swap_date <= s.end_date, *live)
    ):
        entry = db.get(ScheduleEntry, sub.swap_entry_id) if sub.swap_entry_id else None
        if (entry is None or sub.swap_date is None or sub.swap_period_no is None
                or cal.for_entry(entry, sub.swap_date, sub.swap_period_no) is None):
            continue
        absent = db.get(AffectedPeriod, sub.affected_period_id)
        who = absent.leave_request.teacher.name if absent and absent.leave_request.teacher else ""
        out.append(Conflict(sub.swap_date, (
            f"{_md(sub.swap_date)} {sub.swap_period_name} {sub.swap_class_names}:"
            f"{who} 調課回來補課")))

    for cover in db.scalars(
        select(HomeroomCover)
        .join(LeaveRequest, HomeroomCover.leave_request_id == LeaveRequest.id)
        .where(
            HomeroomCover.semester_id == s.semester_id,
            HomeroomCover.date >= s.start_date, HomeroomCover.date <= s.end_date,
            HomeroomCover.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        ).order_by(HomeroomCover.date, HomeroomCover.class_name)
    ):
        if cover.class_id is None or cal.all_day_for_class(cover.class_id, cover.date) is None:
            continue
        who = cover.leave_request.teacher.name if cover.leave_request.teacher else ""
        out.append(Conflict(cover.date, f"{_md(cover.date)} {cover.class_name} 代導:{who}請假"))

    out.sort(key=lambda c: c.date)
    return out
