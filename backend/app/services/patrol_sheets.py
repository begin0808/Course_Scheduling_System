"""巡堂表(巡堂紀錄)的資料組裝(v1.2.12)。

巡堂人員拿著這張紙逐班走:每一節、每一班「現在應該是誰在上什麼課、在哪裡」。
週課表答不了這個問題——調代課之後,那一天的老師、科目可能都換了。這裡把
「已發布的週課表」與「那一天的調代課處置」疊起來,印出當天真正的樣子。

版面照使用學校的紙本:

- **巡堂紀錄**:班級為欄、節次為列,一天分上午/下午各一張(以午休為界;早自習、
  午休等非一般課的時段不列)。每格印科目、教師、教室與備註(代課/調課/…);
  授課情形、學生學習、巡堂簽名留白手寫。班級多的學校自動分頁。
- **分組巡堂單**:社團、多元選修這類「一個時段全校拆成很多組」的跑班群組,
  十幾組塞不進一個格子,另外列成清單(一列一組:名稱、教師、地點)。
  主表那一格只寫群組名稱與組數。

**巡堂人員不在表上。** 紙本是簽名欄,由巡堂的人自己簽;系統不管巡堂輪值。

本模組只讀,不寫資料庫。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import Period, PeriodTable, PeriodType
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import period_tables as pt_service
from app.services import settings as app_settings
from app.services.availability import published_timetable
from app.services.slip_layout import school_title

# dataclass 欄位名 date 會遮蔽同名型別(mypy 判為變數),故型別一律用別名
_Date = date

CLASSES_PER_PAGE = 12       # A4 橫式一頁放得下的班級欄數(照使用學校的紙本)
GROUP_LIST_MIN = 4          # 群組在同一節有幾門課以上,就改列成分組巡堂單
MAX_DAYS = 14               # 一次最多印幾天
_NOON = time(12, 0)

_NOTE = {
    SubstitutionType.substitute.value: "代課",
    SubstitutionType.swap.value: "調課",
    SubstitutionType.merge.value: "併班",
    SubstitutionType.self_study.value: "自習",
    SubstitutionType.cancel.value: "停課",
}
_PENDING = "請假待處理"


@dataclass(frozen=True, slots=True)
class PatrolCell:
    subject: str = ""
    teacher: str = ""
    room: str = ""
    note: str = ""


@dataclass
class PatrolRow:
    ordinal: int              # 第幾節(只數一般課)
    name: str                 # 節次名稱「第一節」
    cells: list[PatrolCell] = field(default_factory=list)   # 與 PatrolPage.classes 一一對應


@dataclass
class PatrolPage:
    date: _Date
    table_name: str           # 全校只有一套節次表時為空字串
    first_ordinal: int        # 抬頭的「第 1~4 節」
    last_ordinal: int
    classes: list[str] = field(default_factory=list)
    rows: list[PatrolRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GroupItem:
    no: int
    subject: str
    teacher: str
    room: str
    note: str


@dataclass
class GroupList:
    date: _Date
    group_name: str
    period_name: str
    items: list[GroupItem] = field(default_factory=list)


@dataclass
class PatrolSheets:
    title: str                # 「示範國中115學年第一學期」
    legend: str               # 紙本下方的記錄說明(各校代碼不同,可在系統管理修改)
    pages: list[PatrolPage] = field(default_factory=list)
    group_lists: list[GroupList] = field(default_factory=list)


class PatrolError(Exception):
    """印不出巡堂表(呼叫端轉 404/400)。"""


@dataclass(frozen=True, slots=True)
class _Lesson:
    """某一班某一節實際上的一門課(已套用當天的調代課)。"""

    unit_id: int
    unit_name: str
    is_group: bool
    subject: str
    teacher: str
    room: str
    note: str


def _days(date_from: date, date_to: date) -> Iterator[date]:
    d = date_from
    while d <= date_to:
        yield d
        d += timedelta(days=1)


def _halves(periods: list[Period]) -> list[list[tuple[int, Period]]]:
    """把一天的一般課切成上午/下午,並編上「第幾節」。

    以午休為界;節次表沒有午休時改以 12:00 為界;兩者都判斷不出來就整天一張。
    """
    ordered = sorted(periods, key=lambda p: p.period_no)
    lunch = next((p.period_no for p in ordered if p.type == PeriodType.lunch.value), None)
    regular = [p for p in ordered if p.type == PeriodType.regular.value]
    numbered = list(enumerate(regular, start=1))

    def is_morning(p: Period) -> bool:
        if lunch is not None:
            return p.period_no < lunch
        return p.start_time is None or p.start_time < _NOON

    morning = [x for x in numbered if is_morning(x[1])]
    afternoon = [x for x in numbered if not is_morning(x[1])]
    return [half for half in (morning, afternoon) if half]


def _same_class(ap: AffectedPeriod, sub: Substitution) -> bool:
    return ap.class_names == sub.swap_class_names


class _Day:
    """某一天的實際課表:週課表格位 + 當天的請假與調代課。"""

    def __init__(self, db: Session, semester_id: int, timetable_id: int, on: date) -> None:
        self.db = db
        self.on = on
        weekday = on.isoweekday()
        self.entries = list(db.scalars(
            select(ScheduleEntry).where(
                ScheduleEntry.timetable_id == timetable_id, ScheduleEntry.weekday == weekday)
        ))
        live = (
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            AffectedPeriod.semester_id == semester_id,
        )
        # 當天請假的節次:(配課, 節次) → (受影響節次, 處置或 None)
        absent = db.scalars(
            select(AffectedPeriod)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(AffectedPeriod.date == on, *live)
        ).unique().all()
        subs = {
            s.affected_period_id: s for s in db.scalars(
                select(Substitution).where(
                    Substitution.affected_period_id.in_([a.id for a in absent] or [0])))
        }
        self.absent: dict[tuple[int | None, int], tuple[AffectedPeriod, Substitution | None]] = {
            (a.course_assignment_id, a.period_no): (a, subs.get(a.id)) for a in absent
        }
        # 當天因調課回來補課的節次:(格位, 節次) → (請假那一節, 調課處置)
        self.makeup: dict[tuple[int | None, int | None], tuple[AffectedPeriod, Substitution]] = {}
        for sub in db.scalars(
            select(Substitution)
            .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                Substitution.type == SubstitutionType.swap.value,
                Substitution.swap_date == on, *live)
        ):
            ap = db.get(AffectedPeriod, sub.affected_period_id)
            if ap is not None:
                self.makeup[(sub.swap_entry_id, sub.swap_period_no)] = (ap, sub)

    def _lesson(self, entry: ScheduleEntry, period_no: int) -> _Lesson:
        a = entry.assignment
        unit = a.scheduling_unit
        room = entry.room if entry.room is not None else a.room
        names = [at.teacher.name for at in a.teachers]
        subject, note = a.subject.name, ""

        def replace(absent_name: str, by: str) -> None:
            """只換掉請假的那一位;協同教學的另一位老師照常上課。"""
            if absent_name in names:
                names[names.index(absent_name)] = by
            else:
                names[:] = [by]

        if (a.id, period_no) in self.absent:
            ap, sub = self.absent[(a.id, period_no)]
            absent_name = ap.leave_request.teacher.name if ap.leave_request.teacher else ""
            if sub is None:
                note = _PENDING
            else:
                note = _NOTE.get(sub.type, "")
                if sub.handler is not None:
                    replace(absent_name, sub.handler.name)
                elif absent_name in names:      # 自習、停課:沒有人接手,請假的那位不會來
                    names.remove(absent_name)
                if sub.type == SubstitutionType.swap.value and _same_class(ap, sub):
                    subject = sub.swap_subject_name or subject   # 同班互調:科目跟著老師走
        elif (entry.id, period_no) in self.makeup:
            ap, sub = self.makeup[(entry.id, period_no)]
            note = _NOTE[SubstitutionType.swap.value]
            partner = sub.handler.name if sub.handler else ""
            back = ap.leave_request.teacher.name if ap.leave_request.teacher else ""
            replace(partner, back)
            if _same_class(ap, sub):
                subject = ap.subject_name or subject

        return _Lesson(
            unit_id=unit.id, unit_name=unit.name, is_group=unit.unit_type == "group",
            subject=subject, teacher="、".join(names), room=room.name if room else "", note=note,
        )

    def lessons(self, class_id: int, period_no: int) -> list[_Lesson]:
        """這一班這一節的課;跑班時會有好幾門(每一組一門),依配課建立的順序排列。

        順序不能看格位:群組的格位是一次整批寫入的,寫入順序取決於資料庫怎麼回傳配課,
        PostgreSQL 並不保證。分組巡堂單的編號要每次都對到同一個社團,故以配課 id 為準。
        """
        out = []
        for e in self.entries:
            if not (e.period_no <= period_no < e.period_no + e.span):
                continue
            if any(m.class_unit_id == class_id for m in e.assignment.scheduling_unit.members):
                out.append((e.course_assignment_id, self._lesson(e, period_no)))
        return [lesson for _, lesson in sorted(out, key=lambda x: x[0])]


def _join(values: list[str], sep: str = "／") -> str:
    return sep.join(dict.fromkeys(v for v in values if v))


def _cell(lessons: list[_Lesson]) -> PatrolCell:
    if not lessons:
        return PatrolCell()
    if lessons[0].is_group and len(lessons) >= GROUP_LIST_MIN:
        return PatrolCell(
            subject=lessons[0].unit_name, teacher=f"共 {len(lessons)} 組", note="見分組巡堂單")
    return PatrolCell(
        subject=_join([x.subject for x in lessons]),
        teacher=_join([x.teacher for x in lessons]),
        room=_join([x.room for x in lessons]),
        note=_join([x.note for x in lessons], "、"),
    )


def legend(db: Session) -> str:
    return app_settings.patrol_legend(db)


def build(db: Session, semester_id: int, date_from: date, date_to: date) -> PatrolSheets:
    """把一段期間的每一天組成巡堂表;沒有課的日子(假日)自動略過。"""
    if date_to < date_from:
        raise PatrolError("結束日期不可早於開始日期")
    if (date_to - date_from).days >= MAX_DAYS:
        raise PatrolError(f"一次最多列印 {MAX_DAYS} 天")
    timetable = published_timetable(db, semester_id)
    if timetable is None:
        raise PatrolError("此學期尚無已發布的課表")

    classes = list(db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    ))
    by_table: dict[int, tuple[PeriodTable, list[ClassUnit]]] = {}
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        if table is not None:
            by_table.setdefault(table.id, (table, []))[1].append(c)
    multi = len(by_table) > 1

    result = PatrolSheets(title=school_title(db, semester_id), legend=legend(db))
    for on in _days(date_from, date_to):
        day = _Day(db, semester_id, timetable.id, on)
        if not day.entries:
            continue
        listed: set[tuple[int, int]] = set()      # 已出過分組單的 (群組, 節次)
        for table, members in by_table.values():
            periods = [p for p in table.periods if p.weekday == on.isoweekday()]
            for half in _halves(periods):
                for i in range(0, len(members), CLASSES_PER_PAGE):
                    chunk = members[i:i + CLASSES_PER_PAGE]
                    page = PatrolPage(
                        date=on, table_name=table.name if multi else "",
                        first_ordinal=half[0][0], last_ordinal=half[-1][0],
                        classes=[c.name for c in chunk],
                    )
                    for ordinal, period in half:
                        row = PatrolRow(ordinal=ordinal, name=period.name)
                        for c in chunk:
                            lessons = day.lessons(c.id, period.period_no)
                            row.cells.append(_cell(lessons))
                            big = lessons and lessons[0].is_group and len(lessons) >= GROUP_LIST_MIN
                            key = (lessons[0].unit_id, period.period_no) if big else None
                            if key and key not in listed:
                                listed.add(key)
                                result.group_lists.append(GroupList(
                                    date=on, group_name=lessons[0].unit_name,
                                    period_name=period.name,
                                    items=[GroupItem(n, x.subject, x.teacher, x.room, x.note)
                                           for n, x in enumerate(lessons, start=1)],
                                ))
                        page.rows.append(row)
                    result.pages.append(page)
    if not result.pages:
        raise PatrolError("這段期間沒有任何課(可能是假日,或課表尚未排入)")
    return result
