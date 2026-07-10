"""調代課處置與代課推薦 schema(M4-2)。"""

from datetime import date

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
