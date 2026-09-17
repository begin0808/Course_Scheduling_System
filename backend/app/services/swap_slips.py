"""調課通知單(教師調課單、班級調課單)的資料組裝(v1.2.2)。

版面照使用學校現行的紙本:一張週課表,只在「有異動的格子」寫上
「日期 / 科目 / 實際上課的老師 / [調MM-DD_星期節次]」,中括號指向對調的另一節。

**一筆調課 = 兩個異動格。** 甲請假那節改由乙上;乙原本那節改由甲上。

- 教師調課單:每位老師一張,只列他「要去上」的那一格(空出來的那一格不列——
  他那節不用去,紙本上也沒有)。
- 班級調課單:每個班一張,列該班所有異動格。

**科目怎麼寫。** 同班互調時,科目跟著老師走(學生只是兩科前後對換):乙在甲那節上乙自己的科目。
跨班對調時乙去的是甲的班、上的是甲那一節的課,科目沿用該節原本的科目。

本模組只讀,不寫資料庫;資料全部來自已成立調課的快照欄位與節次表。
"""

from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import Period, PeriodType
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import period_tables as pt_service
from app.services import settings as app_settings

# dataclass 欄位名 date 會遮蔽同名型別(mypy 判為變數),故型別一律用別名
_Date = date

_TERM_CN = {1: "一", 2: "二", 3: "三"}
_AFTERNOON = time(12, 0)


@dataclass(frozen=True, slots=True)
class SlipRow:
    ordinal: int              # 第幾節(只數一般課,早自習/午休不算)
    start_time: time | None
    end_time: time | None
    afternoon_starts: bool    # 這一列是下午的第一節(紙本在這裡畫粗線)


@dataclass(frozen=True, slots=True)
class SlipCell:
    date: _Date
    weekday: int
    ordinal: int
    subject_name: str
    teacher_name: str
    code: str                 # 「調09-15_25」:與 9/15 星期二第 5 節對調


@dataclass
class SlipWeek:
    monday: _Date
    days: list[_Date] = field(default_factory=list)
    cells: list[SlipCell] = field(default_factory=list)


@dataclass
class Slip:
    kind: str                 # teacher / class
    teacher_name: str         # 教師單才有
    class_names: str
    date_from: _Date
    date_to: _Date
    rows: list[SlipRow] = field(default_factory=list)
    weeks: list[SlipWeek] = field(default_factory=list)


@dataclass
class SwapSlips:
    title: str                # 「示範國中115學年第一學期」
    slips: list[Slip] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Move:
    """一個異動格:某天某節,某班改由某老師上某科。"""

    date: _Date
    period_no: int
    class_names: str
    subject_name: str
    teacher_id: int
    teacher_name: str
    table_id: int | None
    other_date: _Date
    other_period_no: int
    other_table_id: int | None


class SlipError(Exception):
    """要印的不是有效的調課(呼叫端轉 404/409)。"""


class _Tables:
    """節次表快取:算「第幾節」與列出一般課的列。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[int, list[Period]] = {}

    def of_assignment(self, assignment_id: int | None) -> int | None:
        a = self.db.get(CourseAssignment, assignment_id) if assignment_id else None
        if a is None or not a.scheduling_unit.members:
            return None
        table = pt_service.resolve_period_table(self.db, a.scheduling_unit.members[0].class_unit)
        return table.id if table else None

    def regular(self, table_id: int | None, weekday: int) -> list[Period]:
        if table_id is None:
            return []
        if table_id not in self._cache:
            self._cache[table_id] = list(self.db.scalars(
                select(Period).where(Period.period_table_id == table_id)
                .order_by(Period.weekday, Period.period_no)))
        return [p for p in self._cache[table_id]
                if p.weekday == weekday and p.type == PeriodType.regular.value]

    def ordinal(self, table_id: int | None, weekday: int, period_no: int) -> int:
        for i, p in enumerate(self.regular(table_id, weekday), start=1):
            if p.period_no == period_no:
                return i
        return period_no  # 節次表查不到:退回內部節次號,至少不會印空白

    def weekdays(self, table_id: int | None) -> int:
        if table_id is None:
            return 5
        self.regular(table_id, 1)
        return max((p.weekday for p in self._cache[table_id]), default=5)

    def rows(self, table_id: int | None) -> list[SlipRow]:
        periods = self.regular(table_id, 1)
        out: list[SlipRow] = []
        for i, p in enumerate(periods, start=1):
            prev = periods[i - 2] if i > 1 else None
            afternoon = bool(
                prev and prev.start_time and p.start_time
                and prev.start_time < _AFTERNOON <= p.start_time
            )
            out.append(SlipRow(i, p.start_time, p.end_time, afternoon))
        return out


def _title(db: Session, semester_id: int) -> str:
    sem = db.get(Semester, semester_id)
    school = app_settings.school_name(db)
    if sem is None:
        return school
    return f"{school}{sem.academic_year}學年第{_TERM_CN.get(sem.term, str(sem.term))}學期"


def _moves(db: Session, tables: _Tables, ap: AffectedPeriod, sub: Substitution) -> list[_Move]:
    absent = ap.leave_request.teacher
    partner = sub.handler
    if partner is None or sub.swap_date is None or sub.swap_period_no is None:
        raise SlipError("這筆調課資料不完整(對調教師或補課節次已被刪除),無法列印")
    same_class = ap.class_names == sub.swap_class_names
    leave_table = tables.of_assignment(ap.course_assignment_id)
    entry = db.get(ScheduleEntry, sub.swap_entry_id) if sub.swap_entry_id else None
    swap_table = tables.of_assignment(entry.course_assignment_id) if entry else leave_table
    return [
        _Move(  # 請假那節:改由乙上
            date=ap.date, period_no=ap.period_no, class_names=ap.class_names,
            subject_name=sub.swap_subject_name if same_class else ap.subject_name,
            teacher_id=partner.id, teacher_name=partner.name, table_id=leave_table,
            other_date=sub.swap_date, other_period_no=sub.swap_period_no,
            other_table_id=swap_table,
        ),
        _Move(  # 乙原本那節:改由甲上
            date=sub.swap_date, period_no=sub.swap_period_no, class_names=sub.swap_class_names,
            subject_name=ap.subject_name if same_class else sub.swap_subject_name,
            teacher_id=absent.id, teacher_name=absent.name, table_id=swap_table,
            other_date=ap.date, other_period_no=ap.period_no, other_table_id=leave_table,
        ),
    ]


def _slip(tables: _Tables, kind: str, teacher_name: str, moves: list[_Move]) -> Slip:
    table_id = moves[0].table_id
    n_days = tables.weekdays(table_id)
    classes = list(dict.fromkeys(m.class_names for m in moves))
    slip = Slip(
        kind=kind, teacher_name=teacher_name, class_names="、".join(classes),
        date_from=min(m.date for m in moves), date_to=max(m.date for m in moves),
        rows=tables.rows(table_id),
    )
    weeks: dict[_Date, SlipWeek] = {}
    for m in sorted(moves, key=lambda m: (m.date, m.period_no)):
        monday = m.date - timedelta(days=m.date.isoweekday() - 1)
        week = weeks.setdefault(monday, SlipWeek(
            monday=monday, days=[monday + timedelta(days=i) for i in range(n_days)]))
        other_wd = m.other_date.isoweekday()
        other_ord = tables.ordinal(m.other_table_id, other_wd, m.other_period_no)
        week.cells.append(SlipCell(
            date=m.date, weekday=m.date.isoweekday(),
            ordinal=tables.ordinal(m.table_id, m.date.isoweekday(), m.period_no),
            subject_name=m.subject_name, teacher_name=m.teacher_name,
            code=f"調{m.other_date:%m-%d}_{other_wd}{other_ord}",
        ))
    slip.weeks = [weeks[k] for k in sorted(weeks)]
    return slip


def build(db: Session, semester_id: int, affected_ids: list[int]) -> SwapSlips:
    """把指定的調課組成通知單:先每位老師一張(依出場順序),再每個班一張。

    非調課、已撤回或已銷假的節次略過;一筆有效的調課都沒有時拋 `SlipError`。
    """
    rows = db.execute(
        select(AffectedPeriod, Substitution)
        .join(Substitution, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.id.in_(affected_ids),
            AffectedPeriod.semester_id == semester_id,
            Substitution.type == SubstitutionType.swap.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        )
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ).all()
    if not rows:
        raise SlipError("選取的節次中沒有已成立的調課")

    tables = _Tables(db)
    moves: list[_Move] = []
    for ap, sub in rows:
        moves.extend(_moves(db, tables, ap, sub))

    by_teacher: dict[int, list[_Move]] = {}
    by_class: dict[str, list[_Move]] = {}
    for m in moves:
        by_teacher.setdefault(m.teacher_id, []).append(m)
        by_class.setdefault(m.class_names, []).append(m)

    result = SwapSlips(title=_title(db, semester_id))
    for ms in by_teacher.values():
        result.slips.append(_slip(tables, "teacher", ms[0].teacher_name, ms))
    for ms in by_class.values():
        result.slips.append(_slip(tables, "class", "", ms))
    return result
