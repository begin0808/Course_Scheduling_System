"""代課鐘點統計 schema(M4-5)。"""

from datetime import date

from pydantic import BaseModel

_Date = date


class StatDetailOut(BaseModel):
    handler_teacher_id: int
    handler_name: str
    date: _Date
    period_name: str
    class_names: str
    subject_name: str
    absent_teacher_name: str
    leave_type: str
    leave_type_label: str
    sub_type: str
    sub_type_label: str
    counts_toward_hours: bool
    funding_source: str
    pay_kind: str = "none"      # hourly / daily / none
    daily_shared: bool = False  # 日薪:當日與其他日薪代課老師分擔


class CoverDetailOut(BaseModel):
    """代導明細(v1.4.0)。"""

    handler_teacher_id: int
    handler_name: str
    date: _Date
    class_name: str
    part_label: str
    is_half_day: bool
    absent_teacher_name: str
    leave_type_label: str


class TeacherSummaryOut(BaseModel):
    teacher_id: int
    teacher_name: str
    handled_count: int
    billable_count: int          # 鐘點計費節數(不含日薪)
    daily_days: int = 0          # 日薪天數
    daily_periods: int = 0       # 日薪那幾天共代了幾節
    daily_shared_days: int = 0   # 其中幾天與其他日薪代課老師分擔
    cover_full_days: int = 0     # 代導全天(一班一天算一次)
    cover_half_days: int = 0     # 代導半天


class MonthlyReportOut(BaseModel):
    year: int
    month: int
    summaries: list[TeacherSummaryOut] = []
    details: list[StatDetailOut] = []
    cover_details: list[CoverDetailOut] = []
