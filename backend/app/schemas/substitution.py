"""調代課處置與代課推薦 schema(M4-2)。"""

from datetime import date, time

from pydantic import BaseModel, Field


class CandidateOut(BaseModel):
    teacher_id: int
    teacher_name: str
    same_subject: bool
    at_school_that_day: bool
    sub_periods_this_month: int
    reasons: list[str] = []


class RecommendationOut(BaseModel):
    affected_period_id: int
    candidates: list[CandidateOut] = []
    no_candidate_hint: str = ""


class AssignRequest(BaseModel):
    """指派處置。type=substitute/swap/merge 需 handler_teacher_id;swap 另需 swap_*。"""

    type: str  # substitute / swap / merge / self_study / cancel
    handler_teacher_id: int | None = None
    counts_toward_hours: bool | None = None  # 空=依處置預設(代課計、其餘不計)
    funding_source: str = Field(default="", max_length=32)
    # 調課:乙的某節課(schedule_entry)與甲補課的日期
    swap_entry_id: int | None = None
    swap_date: date | None = None
    swap_period_no: int | None = None  # 連堂格位換其中哪一節;空 = 第一節


class SubstitutionOut(BaseModel):
    id: int
    affected_period_id: int
    type: str
    type_label: str
    handler_teacher_id: int | None = None
    handler_name: str | None = None
    counts_toward_hours: bool
    funding_source: str
    swap_date: date | None = None
    swap_period_name: str = ""
    swap_class_names: str = ""
    swap_subject_name: str = ""
    created_by_name: str


class SwapOptionOut(BaseModel):
    entry_id: int
    date: date
    weekday: int
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    same_class: bool
    in_block: bool = False


class SwapPartnerOut(BaseModel):
    teacher_id: int
    teacher_name: str
    teaches_same_class: bool
    blocked_reason: str = ""
    options: list[SwapOptionOut] = []


class SwapOptionsOut(BaseModel):
    """可對調節次:請假那週起數週內,乙能來、甲能補的每一個組合。"""

    affected_period_id: int
    date_from: date
    date_to: date
    partners: list[SwapPartnerOut] = []


# 欄位名 date 會遮蔽同名型別,故以別名標註
_Date = date


class SlipRowOut(BaseModel):
    ordinal: int
    start_time: time | None = None
    end_time: time | None = None
    afternoon_starts: bool = False


class SlipCellOut(BaseModel):
    date: _Date
    weekday: int
    ordinal: int
    subject_name: str
    actor: str  # 第三行:調課單寫上課老師;代課單寫「班級[代]」或「老師[代]」
    code: str


class SlipWeekOut(BaseModel):
    monday: _Date
    days: list[_Date] = []
    cells: list[SlipCellOut] = []


class SlipOut(BaseModel):
    kind: str  # teacher / class
    teacher_name: str = ""
    class_names: str
    date_from: _Date
    date_to: _Date
    absent_teacher_name: str = ""  # 代課單:請假教師
    leave_type_name: str = ""      # 代課單:假別
    funding_label: str = ""        # 代課單:計費方式
    rows: list[SlipRowOut] = []
    weeks: list[SlipWeekOut] = []


class SlipsOut(BaseModel):
    """通知單:先每位教師一張,再每個班一張。"""

    title: str
    kind: str = "swap"  # swap / substitute:決定紙本抬頭
    slips: list[SlipOut] = []
