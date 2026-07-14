"""學期與節次表相關 schema。"""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.period import PeriodType
from app.models.semester import SemesterStatus


class TemplateOut(BaseModel):
    key: str
    name: str
    minutes_per_period: int
    subject_count: int


# ── 節次 ──────────────────────────────
class PeriodIn(BaseModel):
    weekday: int = Field(ge=1, le=6)
    period_no: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=32)
    start_time: time | None = None
    end_time: time | None = None
    type: PeriodType = PeriodType.regular


class PeriodOut(PeriodIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AvailableSlot(BaseModel):
    """可排課時段(type=regular 的格位)。"""

    weekday: int
    period_no: int
    name: str
    start_time: time | None = None
    end_time: time | None = None


# ── 節次表 ────────────────────────────
class PeriodTableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    num_weekdays: int
    is_default: bool
    periods: list[PeriodOut] = []


class PeriodTableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    num_weekdays: int = Field(default=5, ge=5, le=6)
    is_default: bool = False
    # 若指定,依此學制範本帶入節次;否則建立空表
    template_key: str | None = None


class PeriodTableUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_default: bool | None = None


# ── 學期 ──────────────────────────────
class SemesterCreate(BaseModel):
    academic_year: int = Field(ge=100, le=200)  # 民國學年度
    term: int = Field(ge=1, le=2)
    start_date: date | None = None
    end_date: date | None = None
    # 若指定,依此學制範本帶入預設節次表
    template_key: str | None = None


class SemesterUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    status: SemesterStatus | None = None


class SemesterCopyRequest(BaseModel):
    academic_year: int = Field(ge=100, le=200)
    term: int = Field(ge=1, le=2)
    # 新學期的起訖日:不能沿用來源學期(那是上學期的日期)。少了它,請假展開、今日看板、
    # 代課的「已上過」判定全部失準,而且畫面上看不出哪裡不對(M6-4)。
    start_date: date | None = None
    end_date: date | None = None
    period_tables: bool = True
    subjects: bool = True
    teachers: bool = True
    rooms: bool = True
    classes: bool = True
    grade_promotion: bool = True
    constraint_config: bool = True  # 軟約束權重(不帶則新學期悄悄回到預設值)

    @model_validator(mode="after")
    def _dates_in_order(self) -> "SemesterCopyRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("學期結束日不可早於開始日")
        return self


class SemesterListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    academic_year: int
    term: int
    label: str
    status: SemesterStatus
    start_date: date | None = None
    end_date: date | None = None


class SemesterOut(SemesterListItem):
    period_tables: list[PeriodTableOut] = []
