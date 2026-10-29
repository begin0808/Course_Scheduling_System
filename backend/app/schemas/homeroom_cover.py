"""代導 schema(v1.4.0)。"""

from datetime import date

from pydantic import BaseModel

from app.schemas.leave import HomeroomCoverOut

_Date = date


class CoverOptionOut(BaseModel):
    teacher_id: int
    teacher_name: str
    group: str        # same_grade_homeroom / class_teacher / other
    group_label: str  # 同年級導師 / 該班任課老師 / 其他老師
    note: str         # 「702 導師」「教 701 國文」


class CoverOptionsOut(BaseModel):
    options: list[CoverOptionOut] = []


class CoverAssignIn(BaseModel):
    handler_teacher_id: int | None = None
    no_cover: bool = False      # 標記「不需代導」
    whole_leave: bool = False   # 同一張假單、同一班其他還沒安排的日子一起指派


class CoverSkipOut(BaseModel):
    cover_id: int
    date: _Date
    class_name: str
    reason: str


class CoverAssignOut(BaseModel):
    assigned: int
    skipped: list[CoverSkipOut] = []


class CoverLogOut(HomeroomCoverOut):
    """代導紀錄的一列:多帶請假導師與假別。"""

    absent_teacher_name: str
    leave_type_label: str


class CoverSlipRowOut(BaseModel):
    date: _Date
    weekday: int
    part_label: str
    class_name: str
    absent_teacher_name: str
    leave_type_label: str


class CoverSlipOut(BaseModel):
    teacher_name: str
    rows: list[CoverSlipRowOut] = []


class CoverSlipsOut(BaseModel):
    school_name: str
    semester_label: str
    slips: list[CoverSlipOut] = []
