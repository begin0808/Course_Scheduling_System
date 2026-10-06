"""今日看板與調代課日誌 schema(M4-4)。"""

from datetime import date, time

from pydantic import BaseModel

# 欄位名 date/start_time 會遮蔽同名型別,故以別名標註型別
_Date = date
_Time = time


class LogEntryOut(BaseModel):
    affected_period_id: int
    date: _Date
    weekday: int
    period_no: int
    period_name: str
    start_time: _Time | None = None
    end_time: _Time | None = None
    class_names: str
    subject_name: str
    room_name: str
    absent_teacher_id: int
    absent_teacher_name: str
    leave_type: str
    leave_type_label: str
    status: str
    status_label: str
    disposed: bool
    sub_type: str | None = None
    sub_type_label: str | None = None
    handler_teacher_id: int | None = None
    handler_name: str | None = None
    counts_toward_hours: bool | None = None
    swap_date: _Date | None = None
    swap_period_name: str = ""
    swap_class_names: str = ""
    swap_subject_name: str = ""
    note: str = ""
    row_kind: str = "leave"  # leave / swap_makeup(調課補課日被換來的那一節)


class PatrolCellOut(BaseModel):
    subject: str
    teacher: str
    room: str
    note: str


class PatrolRowOut(BaseModel):
    ordinal: int
    name: str
    cells: list[PatrolCellOut]


class PatrolPageOut(BaseModel):
    date: _Date
    table_name: str
    first_ordinal: int
    last_ordinal: int
    classes: list[str]
    rows: list[PatrolRowOut]


class PatrolGroupItemOut(BaseModel):
    no: int
    subject: str
    teacher: str
    room: str
    note: str


class PatrolGroupListOut(BaseModel):
    date: _Date
    group_name: str
    period_name: str
    items: list[PatrolGroupItemOut]


class PatrolSheetsOut(BaseModel):
    """巡堂表列印資料:巡堂紀錄(班級為欄)+ 分組巡堂單(社團等大型跑班群組)。"""

    title: str
    legend: str
    pages: list[PatrolPageOut]
    group_lists: list[PatrolGroupListOut]


class DailyBoardOut(BaseModel):
    """今日看板:表頭(校名/日期/學期)供列印通知單直接使用。"""

    date: _Date
    weekday: int
    school_name: str
    semester_label: str
    entries: list[LogEntryOut] = []
