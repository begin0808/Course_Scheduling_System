"""課表查詢的「某一週實際課表」(v1.4.15)。

老師建議:課表查詢只看得到固定的週課表,想看某一週調代課之後真正的樣子,
而且有異動的格子要標出來。資料與巡堂表、教師週總表同一份(`patrol_sheets.Day`:
已發布課表疊上當天的調代課,單雙週只列當週的課)。

- 班級課表:每一節實際來上課的老師;有異動時標出種類,並寫原本的老師。
- 教師課表:與教師週總表同一套——原本的課沒上劃掉並寫去向,代別人的課、調課來上的課標色。

場地課表不提供週次(調代課不會改場地)。本模組只讀,不寫資料庫。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Teacher
from app.models.semester import Semester
from app.services import period_tables as pt_service
from app.services import teacher_week_sheets as tw
from app.services.availability import published_timetable
from app.services.patrol_sheets import GRID_GROUP_LIST_MIN, Day, _Lesson, join
from app.services.slip_layout import Tables

_Date = date

# 班級課表的異動種類:巡堂表的備註 → 格子樣式(與教師週總表同一套顏色)
_KIND = {
    "代課": tw.COVER, "併班": tw.COVER, "調課": tw.SWAP,
    "自習": tw.OFF, "停課": tw.OFF, "請假待處理": tw.PENDING,
}


@dataclass(frozen=True, slots=True)
class WeekCell:
    date: _Date
    weekday: int
    ordinal: int            # 第幾節(只數一般課)
    period_no: int | None   # 班級課表:該班節次表的節次;教師課表為 None(前端依第幾節對到格線)
    subject: str
    teacher: str
    room: str
    kind: str               # normal / off / pending / cover / swap
    note: str               # 「代課(原:王師)」「陳師代」「調10/30_56」


@dataclass
class TimetableWeek:
    monday: _Date
    dates: list[_Date] = field(default_factory=list)    # 週一到週日,畫面表頭寫日期用
    cells: list[WeekCell] = field(default_factory=list)


class TimetableWeekError(Exception):
    """產生不出週課表(呼叫端轉 404/400)。"""


def _in_term(semester: Semester | None, d: date) -> bool:
    if semester is None:
        return True
    if semester.start_date and d < semester.start_date:
        return False
    return not (semester.end_date and d > semester.end_date)


def _note(x: _Lesson) -> str:
    """「代課(原:王師)」;調課再寫出對調的另一節,另一半可能在隔天或別週(v1.4.17,組長回報:
    補課排在隔天,只看到一格變色,以為只有一個人被調)。"""
    extra = [f"原:{x.original}"] if x.original and x.teacher != x.original else []
    if x.swap_with:
        extra.append(f"與 {x.swap_with}對調")
    return f"{x.note}({','.join(extra)})" if extra else x.note


def _class_cells(db: Session, day: Day, klass: ClassUnit, tables: Tables) -> list[WeekCell]:
    pt = pt_service.resolve_period_table(db, klass)
    table = pt.id if pt else None
    out = []
    for ordinal, period in enumerate(tables.regular(table, day.on.isoweekday()), start=1):
        lessons = day.lessons(klass.id, period.period_no)
        if not lessons:
            continue
        notes = [x.note for x in lessons if x.note]
        kind = next((_KIND.get(n, tw.NORMAL) for n in notes), tw.NORMAL)
        note = join([_note(x) for x in lessons if x.note], "、")
        big = lessons[0].is_group and len(lessons) >= GRID_GROUP_LIST_MIN
        out.append(WeekCell(
            date=day.on, weekday=day.on.isoweekday(), ordinal=ordinal,
            period_no=period.period_no,
            subject=lessons[0].unit_name if big else join([x.subject for x in lessons]),
            teacher=f"共 {len(lessons)} 組" if big else join([x.teacher for x in lessons]),
            room="" if big else join([x.room for x in lessons]),
            kind=kind, note=note,
        ))
    return out


def _teacher_cells(b: tw.Builder, day: Day, teacher_id: int) -> list[WeekCell]:
    cells = tw.day_cells(b, day)
    out = []
    for (tid, ordinal), items in sorted(cells.items(), key=lambda x: x[0][1]):
        if tid != teacher_id or not items:
            continue
        first = next((x for x in items if x.kind != tw.NORMAL), items[0])
        out.append(WeekCell(
            date=day.on, weekday=day.on.isoweekday(), ordinal=ordinal, period_no=None,
            subject=join([x.text for x in items]), teacher="", room="",
            kind=first.kind, note=join([x.note for x in items if x.note], "、"),
        ))
    return out


def build(db: Session, semester_id: int, view: str, target_id: int, on: date) -> TimetableWeek:
    timetable = published_timetable(db, semester_id)
    if timetable is None:
        raise TimetableWeekError("此學期尚無已發布的課表")
    semester = db.get(Semester, semester_id)
    monday = on - timedelta(days=on.isoweekday() - 1)
    result = TimetableWeek(monday=monday, dates=[monday + timedelta(days=i) for i in range(7)])

    klass: ClassUnit | None = None
    if view == "class":
        klass = db.get(ClassUnit, target_id)
        if klass is None or klass.semester_id != semester_id:
            raise TimetableWeekError("找不到這個班級")
    elif view == "teacher":
        teacher = db.get(Teacher, target_id)
        if teacher is None or teacher.semester_id != semester_id:
            raise TimetableWeekError("找不到這位老師")
    else:
        raise TimetableWeekError("只有班級、教師課表可以看某一週")

    b = tw.Builder(db, semester_id)
    for d in result.dates:
        if not _in_term(semester, d):
            continue
        day = Day(db, semester_id, timetable.id, d)
        if not day.entries:
            continue
        if klass is not None:
            result.cells.extend(_class_cells(db, day, klass, b.tables))
        else:
            result.cells.extend(_teacher_cells(b, day, target_id))
    return result
