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


class TeacherSummaryOut(BaseModel):
    teacher_id: int
    teacher_name: str
    handled_count: int
    billable_count: int


class MonthlyReportOut(BaseModel):
    year: int
    month: int
    summaries: list[TeacherSummaryOut] = []
    details: list[StatDetailOut] = []
