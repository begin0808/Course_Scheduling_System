"""學期與節次表相關 schema。"""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field

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
    period_tables: bool = True
    subjects: bool = True
    teachers: bool = True
    rooms: bool = True
    classes: bool = True
    grade_promotion: bool = True


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
