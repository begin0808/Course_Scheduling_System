"""通知單(調課單、代課單)共用的版面組裝。

紙本一律是一張週課表,只在「有異動的格子」寫上日期、科目與一行說明;
格線、節次列、下午粗線、跨週分頁都一樣。調課單(v1.2.2)與代課單(v1.2.5)
差在表頭欄位與格子裡那一行字,故把相同的部分抽在這裡共用。

本模組只讀,不寫資料庫;資料全部來自處置的快照欄位與節次表。
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.period import Period, PeriodType
from app.models.semester import Semester
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
    actor: str                # 第三行:調課單寫實際上課的老師;代課單寫「班級[代]」或「老師[代]」
    code: str                 # 調課單的「調09-15_25」(與 9/15 星期二第 5 節對調);代課單沒有


@dataclass
class SlipWeek:
    monday: _Date
    days: list[_Date] = field(default_factory=list)
    cells: list[SlipCell] = field(default_factory=list)


@dataclass
class Slip:
    kind: str                 # teacher / class
    teacher_name: str         # 教師單的主角:調課教師 / 代課教師
    class_names: str
    date_from: _Date
    date_to: _Date
    absent_teacher_name: str = ""   # 代課單才有:請假教師
    leave_type_name: str = ""       # 代課單才有:假別
    funding_label: str = ""         # 代課單才有:計費方式
    rows: list[SlipRow] = field(default_factory=list)
    weeks: list[SlipWeek] = field(default_factory=list)


@dataclass
class Slips:
    title: str                # 調課單「示範國中115學年第一學期」;代課單只有校名
    kind: str = "swap"        # swap / substitute:決定紙本抬頭
    slips: list[Slip] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Move:
    """一個異動格:某天某節,某班改由某老師上某科。"""

    date: _Date
    period_no: int
    class_names: str
    subject_name: str
    teacher_id: int
    teacher_name: str
    table_id: int | None
    code: str = ""            # 調課單的對調代碼
    mark: str = ""            # 接在人名/班級後的標記,如「[代]」「[併]」


class SlipError(Exception):
    """要印的不是有效的處置(呼叫端轉 404/409)。"""


class Tables:
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


def school_title(db: Session, semester_id: int | None = None) -> str:
    """校名;給了學期就再接「115學年第一學期」(調課單紙本有,代課單沒有)。"""
    school = app_settings.school_name(db)
    sem = db.get(Semester, semester_id) if semester_id else None
    if sem is None:
        return school
    return f"{school}{sem.academic_year}學年第{_TERM_CN.get(sem.term, str(sem.term))}學期"


def assemble(
    tables: Tables, kind: str, teacher_name: str, moves: list[Move],
    actor_of: Callable[[Move], str],
) -> Slip:
    """把異動格排進週課表:跨週會產生多個 `SlipWeek`(列印頁一週一頁)。"""
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
        week.cells.append(SlipCell(
            date=m.date, weekday=m.date.isoweekday(),
            ordinal=tables.ordinal(m.table_id, m.date.isoweekday(), m.period_no),
            subject_name=m.subject_name, actor=actor_of(m), code=m.code,
        ))
    slip.weeks = [weeks[k] for k in sorted(weeks)]
    return slip
