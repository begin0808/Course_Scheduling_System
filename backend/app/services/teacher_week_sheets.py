"""全校教師週總表(含調代課)(v1.4.14)。

設備組長回報:學校習慣手做一張「全校老師一週總表」貼在辦公室,標出這週誰請假、
誰代誰、誰和誰調課,老師一眼就看得到自己這週要多上或少上哪幾節。

版面照那張手做的表:

- 一週一張;**老師為欄**(先行政職、再依班級排導師、其餘照建檔順序),
  **日期 × 節次為列**(只列一般課,沒有課的日子略過)。
- 格子寫「班級 科目」。有異動時:
  - 原本的課沒上(請假、對調出去):劃掉,後面寫去向(陳師代、調給陳師、自習…)。
  - 代別人的課(代課、併班):藍字,後面寫「代王師」。
  - 調課來上的課:紅字,後面寫對調另一節的記號(與調課單同一套,例如 調10/30_56)。

資料與巡堂表同一份(`patrol_sheets.Day`):已發布的週課表疊上當天的調代課,
單雙週只列當週有上的課。本模組只讀,不寫資料庫。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Teacher
from app.models.leave import AffectedPeriod
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services.availability import published_timetable
from app.services.patrol_sheets import Day, classes_by_period_table
from app.services.slip_layout import Tables, school_title

_Date = date

MAX_WEEKS = 4
_CN_ORDINAL = "一二三四五六七八九十"

# 格子裡每一筆的樣式
NORMAL = "normal"     # 照常上課
OFF = "off"           # 原本的課沒上(劃掉)
PENDING = "pending"   # 請假還沒安排(劃掉,橘字)
COVER = "cover"       # 代別人的課(藍字)
SWAP = "swap"         # 調課來上的課(紅字)

LEGEND = "紅字:調課(記號指向對調的另一節)　藍字:代課、併班　劃線:原本的課沒上"


@dataclass(frozen=True, slots=True)
class Item:
    text: str           # 「801 數學」
    kind: str = NORMAL
    note: str = ""      # 「陳師代」「代王師」「調10/30_56」


@dataclass(frozen=True, slots=True)
class TeacherCol:
    id: int
    name: str
    role: str           # 「教務主任」「801導師」;都不是時為空字串


@dataclass
class WeekRow:
    date: _Date
    ordinal: int
    period_name: str
    cells: list[list[Item]] = field(default_factory=list)   # 與 teachers 一一對應


@dataclass
class Week:
    monday: _Date
    rows: list[WeekRow] = field(default_factory=list)


@dataclass
class TeacherWeekSheets:
    title: str
    legend: str
    teachers: list[TeacherCol] = field(default_factory=list)
    weeks: list[Week] = field(default_factory=list)


class TeacherWeekError(Exception):
    """產生不出週總表(呼叫端轉 404/400)。"""


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _days(monday: date) -> Iterator[date]:
    for i in range(7):
        yield monday + timedelta(days=i)


def _columns(db: Session, semester_id: int) -> list[TeacherCol]:
    """行政職在前,再依班級順序排導師,其餘照建檔順序(多半就是學校匯入的順序)。"""
    teachers = list(db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id, Teacher.is_active.is_(True))
        .order_by(Teacher.id)))
    homeroom: dict[int, tuple[int, str]] = {}
    for rank, c in enumerate(db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    )):
        if c.homeroom_teacher_id is not None and c.homeroom_teacher_id not in homeroom:
            homeroom[c.homeroom_teacher_id] = (rank, c.name)

    def key(t: Teacher) -> tuple[int, int]:
        if t.admin_title:
            return (0, 0)
        if t.id in homeroom:
            return (1, homeroom[t.id][0])
        return (2, 0)

    out = []
    for t in sorted(teachers, key=key):        # sorted 穩定:同一組內維持建檔順序
        if t.admin_title:
            role = t.admin_title
        elif t.id in homeroom:
            role = f"{homeroom[t.id][1]}導師"
        else:
            role = ""
        out.append(TeacherCol(id=t.id, name=t.name, role=role))
    return out


class _Builder:
    def __init__(self, db: Session, semester_id: int) -> None:
        self.db = db
        self.semester_id = semester_id
        self.tables = Tables(db)
        self._table_of: dict[int, int | None] = {}

    def table_of(self, assignment_id: int | None) -> int | None:
        if assignment_id is None:
            return None
        if assignment_id not in self._table_of:
            self._table_of[assignment_id] = self.tables.of_assignment(assignment_id)
        return self._table_of[assignment_id]

    def ordinal(self, assignment_id: int | None, weekday: int, period_no: int) -> int:
        return self.tables.ordinal(self.table_of(assignment_id), weekday, period_no)

    def swap_code(self, on: date, assignment_id: int | None, period_no: int) -> str:
        wd = on.isoweekday()
        return f"調{_md(on)}_{wd}{self.ordinal(assignment_id, wd, period_no)}"

    def entry_assignment(self, entry_id: int | None) -> int | None:
        entry = self.db.get(ScheduleEntry, entry_id) if entry_id else None
        return entry.course_assignment_id if entry else None


def _label(entry: ScheduleEntry) -> str:
    a = entry.assignment
    unit = a.scheduling_unit
    if unit.unit_type == "group":
        names = [m.class_unit.name for m in unit.members]
        classes = "、".join(names) if len(names) <= 3 else unit.name
    else:
        classes = unit.name
    return f"{classes} {a.subject.name}"


def _snap(classes: str, subject: str) -> str:
    return f"{classes} {subject}".strip()


def _off_note(sub: Substitution | None) -> tuple[str, str]:
    """請假那一節:老師自己的欄寫去向。"""
    if sub is None:
        return PENDING, "請假待處理"
    who = sub.handler.name if sub.handler else ""
    match sub.type:
        case SubstitutionType.substitute.value:
            return OFF, f"{who}代"
        case SubstitutionType.swap.value:
            return OFF, f"調給{who}"
        case SubstitutionType.merge.value:
            return OFF, f"併入{who}"
        case SubstitutionType.self_study.value:
            return OFF, "自習"
        case _:
            return OFF, "停課"


def _day_cells(b: _Builder, day: Day) -> dict[tuple[int, int], list[Item]]:
    """這一天每位老師每一節的格子:(教師, 第幾節) → 格子內容。"""
    out: dict[tuple[int, int], list[Item]] = {}
    wd = day.on.isoweekday()

    def put(teacher_id: int | None, ordinal: int, item: Item) -> None:
        if teacher_id is not None:
            out.setdefault((teacher_id, ordinal), []).append(item)

    for e in sorted(day.entries, key=lambda x: (x.period_no, x.course_assignment_id)):
        a = e.assignment
        teacher_ids = [at.teacher_id for at in a.teachers]
        label = _label(e)
        for p in range(e.period_no, e.period_no + e.span):
            ordinal = b.ordinal(a.id, wd, p)
            if (a.id, p) in day.absent:
                ap, sub = day.absent[(a.id, p)]
                absent_id = ap.leave_request.teacher_id
                for t in teacher_ids:          # 協同教學的另一位照常上課
                    if t != absent_id:
                        put(t, ordinal, Item(label))
                kind, note = _off_note(sub)
                put(absent_id, ordinal, Item(label, kind, note))
                if sub is not None and sub.handler is not None:
                    put(sub.handler_teacher_id, ordinal, _taken_over(b, ap, sub))
            elif (e.id, p) in day.makeup:
                ap, sub = day.makeup[(e.id, p)]
                partner_id = sub.handler_teacher_id
                absent = ap.leave_request.teacher
                for t in teacher_ids:
                    if t != partner_id:
                        put(t, ordinal, Item(label))
                put(partner_id, ordinal, Item(label, OFF, f"調給{absent.name if absent else ''}"))
                same_class = ap.class_names == sub.swap_class_names
                subject = ap.subject_name if same_class else sub.swap_subject_name
                put(ap.leave_request.teacher_id, ordinal, Item(
                    _snap(sub.swap_class_names, subject), SWAP,
                    b.swap_code(ap.date, ap.course_assignment_id, ap.period_no)))
            else:
                for t in teacher_ids:
                    put(t, ordinal, Item(label))
    return out


def _taken_over(b: _Builder, ap: AffectedPeriod, sub: Substitution) -> Item:
    """接手請假那一節的老師:代課、併班藍字;調課紅字並標補課那一節。"""
    absent = ap.leave_request.teacher
    absent_name = absent.name if absent else ""
    if sub.type == SubstitutionType.swap.value and sub.swap_date and sub.swap_period_no:
        same_class = ap.class_names == sub.swap_class_names
        subject = sub.swap_subject_name if same_class else ap.subject_name
        code = b.swap_code(sub.swap_date, b.entry_assignment(sub.swap_entry_id),
                           sub.swap_period_no)
        return Item(_snap(ap.class_names, subject), SWAP, code)
    verb = "併" if sub.type == SubstitutionType.merge.value else "代"
    return Item(_snap(ap.class_names, ap.subject_name), COVER, f"{verb}{absent_name}")


def _row_names(b: _Builder, tables: list[int], weekday: int) -> list[str]:
    """這一天的節次名稱。`tables` 第一個是班級最多的那套節次表,名稱以它為準;
    別套節次表節數較多時(例如國中部有第八節),多出來的列補上「第八節」。"""
    if not tables:
        return []
    names = [p.name for p in b.tables.regular(tables[0], weekday)]
    longest = max(len(b.tables.regular(t, weekday)) for t in tables)
    return names + [f"第{_CN_ORDINAL[i] if i < 10 else i + 1}節"
                    for i in range(len(names), longest)]


def build(db: Session, semester_id: int, on: date, weeks: int = 1) -> TeacherWeekSheets:
    """從 `on` 那一週的週一起,連續 `weeks` 週,每週一張。"""
    if not 1 <= weeks <= MAX_WEEKS:
        raise TeacherWeekError(f"一次最多 {MAX_WEEKS} 週")
    timetable = published_timetable(db, semester_id)
    if timetable is None:
        raise TeacherWeekError("此學期尚無已發布的課表")
    semester = db.get(Semester, semester_id)

    b = _Builder(db, semester_id)
    by_table = sorted(classes_by_period_table(db, semester_id).values(), key=lambda x: -len(x[1]))
    tables = [t.id for t, _ in by_table]
    result = TeacherWeekSheets(
        title=school_title(db, semester_id), legend=LEGEND,
        teachers=_columns(db, semester_id))
    first_monday = on - timedelta(days=on.isoweekday() - 1)
    for w in range(weeks):
        week = Week(monday=first_monday + timedelta(days=7 * w))
        for d in _days(week.monday):
            if semester and semester.start_date and d < semester.start_date:
                continue
            if semester and semester.end_date and d > semester.end_date:
                continue
            day = Day(db, semester_id, timetable.id, d)
            if not day.entries:
                continue
            cells = _day_cells(b, day)
            for ordinal, name in enumerate(_row_names(b, tables, d.isoweekday()), 1):
                week.rows.append(WeekRow(
                    date=d, ordinal=ordinal, period_name=name,
                    cells=[cells.get((t.id, ordinal), []) for t in result.teachers]))
        if week.rows:
            result.weeks.append(week)
    if not result.weeks:
        raise TeacherWeekError("這段期間沒有任何課(可能是假日、不在學期內,或課表尚未排入)")
    return result
