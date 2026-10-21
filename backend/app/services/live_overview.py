"""儀表板「即時概況」(v1.3.3):現在這一節,各班實際在上什麼課、誰在上。

起因(使用者 Issue #50):儀表板只有資料筆數與今日異動數,看不出「現在這一節各班在上什麼」。

巡堂表已經把「已發布課表 + 當天的調代課」疊成那一天每班每節的實際樣子(含單雙週、
跨部作息,見 `patrol_sheets.Day`),這裡只取「現在」那一節。現在是第幾節,依各班**自己的
節次表**的上下課時間判斷,所以國中小兩套作息的學校,同一時刻兩部可能在不同節,分開列。

使用者定案:
- 下課、早自習、午休時,列出**下一節**各班的課,讓組長先確認有沒有缺人。
- 上學前、放學後、沒有課的日子只顯示一行說明。
- 節次表沒填上下課時間就無從判斷現在是第幾節,請組長去填。

本模組只讀,不寫資料庫。
"""

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit
from app.models.period import Period, PeriodType
from app.models.semester import Semester
from app.services import patrol_sheets
from app.services.availability import published_timetable


class LiveState(enum.StrEnum):
    in_class = "in_class"           # 正在上課:列出這一節
    upcoming = "upcoming"           # 下課、早自習、午休:列出下一節
    before_school = "before_school"
    after_school = "after_school"
    no_class = "no_class"           # 今天沒有課(假日、這天沒有節次或沒有排課)
    no_times = "no_times"           # 節次表沒填上下課時間


@dataclass(frozen=True, slots=True)
class LiveCell:
    class_name: str
    subject: str = ""
    teacher: str = ""
    room: str = ""
    note: str = ""      # 代課/調課/併班/自習/停課/請假待處理


@dataclass
class LiveSection:
    """一套節次表(全校只有一套時就只有這一段)。"""

    table_name: str     # 全校只有一套節次表時為空
    state: str
    message: str = ""   # 不列課表時的一行說明
    now_label: str = "" # 現在是什麼時段:「下課」「午休」「早自習」;上課中為空
    period_name: str = ""
    start: str = ""
    end: str = ""
    cells: list[LiveCell] = field(default_factory=list)


@dataclass
class LiveOverview:
    date: date
    weekday: int
    time: str
    message: str = ""   # 整體無法顯示的原因(沒有已發布課表、不在學期期間)
    sections: list[LiveSection] = field(default_factory=list)


def _hhmm(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def _cell(klass: ClassUnit, lessons: list) -> LiveCell:
    if not lessons:
        return LiveCell(class_name=klass.name)
    if lessons[0].is_group and len(lessons) >= patrol_sheets.GROUP_LIST_MIN:
        # 社團這類大型跑班一格塞不下,只寫群組名稱與組數(同巡堂表)
        return LiveCell(class_name=klass.name, subject=lessons[0].unit_name,
                        teacher=f"共 {len(lessons)} 組")
    j = patrol_sheets.join
    return LiveCell(
        class_name=klass.name,
        subject=j([x.subject for x in lessons]),
        teacher=j([x.teacher for x in lessons]),
        room=j([x.room for x in lessons]),
        note=j([x.note for x in lessons], "、"),
    )


def _section(periods: list[Period], now: time) -> tuple[LiveSection, Period | None]:
    """判斷這套節次表「現在」的狀態,回傳 (狀態, 要列出的那一節)。"""
    regular = [p for p in periods if p.type == PeriodType.regular.value]
    if not regular:
        return LiveSection("", LiveState.no_class, "今天沒有課"), None
    if any(p.start_time is None or p.end_time is None for p in regular):
        return LiveSection(
            "", LiveState.no_times,
            "節次表沒有填上下課時間,無法判斷現在是第幾節;"
            "請到「基礎資料 → 學期與節次表」補上。",
        ), None
    regular.sort(key=lambda p: p.start_time or time.min)
    timed = [p for p in periods if p.start_time is not None]
    first = min(p.start_time for p in timed if p.start_time)
    if now < first:
        return LiveSection(
            "", LiveState.before_school,
            f"還沒到上課時間({regular[0].name} {_hhmm(regular[0].start_time)} 開始)",
        ), None
    if now >= max(p.end_time for p in regular if p.end_time):
        return LiveSection("", LiveState.after_school, "今天的課已結束"), None

    for p in regular:
        if p.start_time and p.end_time and p.start_time <= now < p.end_time:
            return LiveSection("", LiveState.in_class), p
    nxt = next(p for p in regular if p.start_time and p.start_time > now)
    during = next(
        (p.name for p in timed
         if p.start_time and p.end_time and p.start_time <= now < p.end_time),
        "下課",
    )
    return LiveSection("", LiveState.upcoming, now_label=during), nxt


def build(db: Session, semester_id: int, now: datetime) -> LiveOverview:
    """`now` 為學校時區的現在(呼叫端傳入,測試可指定時刻)。"""
    today = now.date()
    result = LiveOverview(date=today, weekday=today.isoweekday(), time=now.strftime("%H:%M"))
    semester = db.get(Semester, semester_id)
    if semester is not None and (
        (semester.start_date and today < semester.start_date)
        or (semester.end_date and today > semester.end_date)
    ):
        result.message = "今天不在這個學期的起訖日期內"
        return result
    timetable = published_timetable(db, semester_id)
    if timetable is None:
        result.message = "這個學期還沒有發布課表"
        return result

    by_table = patrol_sheets.classes_by_period_table(db, semester_id)
    if not by_table:
        result.message = "這個學期還沒有班級"
        return result
    day = patrol_sheets.Day(db, semester_id, timetable.id, today)
    multi = len(by_table) > 1
    for table, members in by_table.values():
        periods = [p for p in table.periods if p.weekday == today.isoweekday()]
        if not day.entries:
            section, period = LiveSection("", LiveState.no_class, "今天沒有課"), None
        else:
            section, period = _section(periods, now.time())
        section.table_name = table.name if multi else ""
        if period is not None:
            section.period_name = period.name
            section.start, section.end = _hhmm(period.start_time), _hhmm(period.end_time)
            section.cells = [_cell(c, day.lessons(c.id, period.period_no)) for c in members]
        result.sections.append(section)
    return result
