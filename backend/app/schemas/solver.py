"""排課引擎相關 schema(pre-flight 報告、軟約束設定與達成度)。"""

from pydantic import BaseModel, Field


class PreflightIssue(BaseModel):
    level: str  # error / warning
    code: str
    message: str
    subject_type: str  # teacher / class / room / assignment / semester
    subject_id: int
    detail: dict = {}


class PreflightOut(BaseModel):
    """排課前置檢查報告。ok=False 時 errors 必然非空,自動排課應被擋下。"""

    semester_id: int
    semester_label: str
    ok: bool
    error_count: int
    warning_count: int
    issues: list[PreflightIssue] = []
    # 供 UI 顯示規模
    class_count: int
    teacher_count: int
    assignment_count: int
    total_periods: int


# ── 軟約束設定與達成度(M3-3)────────────
class ConstraintConfigIn(BaseModel):
    """權重 0 = 關閉該項軟約束。設定 UI 於 v2 才做,先以 API 調整。"""

    daily_subject_cap: int = Field(default=2, ge=1, le=8)
    teacher_daily_max: int = Field(default=6, ge=1, le=12)
    teacher_consecutive_max: int = Field(default=3, ge=1, le=12)
    weights: dict[str, int] = {}


class ConstraintConfigOut(ConstraintConfigIn):
    semester_id: int
    weight_names: dict[str, str] = {}  # S1 → 「教師偏好時段」


class SoftScoreOut(BaseModel):
    code: str
    name: str
    weight: int
    opportunities: int  # 滿分
    satisfied: int      # 得分
    violations: int
    penalty: int
    rate: float
    details: list[str] = []


class SoftReportOut(BaseModel):
    total_penalty: int
    items: list[SoftScoreOut] = []


# ── 衝突定位與部分排課(M3-5)──────────
class ConflictCauseOut(BaseModel):
    code: str  # H3 / H4 / H9 / H10 / structural,或 pre-flight 檢查代碼
    scope_type: str
    scope_id: int
    scope_name: str
    message: str  # 人話 + 具體數字
    suggestion: str
    relaxable: bool = False
    detail: dict = {}


class ConflictReportOut(BaseModel):
    status: str
    source: str  # preflight / analysis / none
    mode: str  # each / joint / structural
    headline: str
    complete: bool = True
    relaxable_codes: list[str] = []
    causes: list[ConflictCauseOut] = []


class RelaxableOption(BaseModel):
    code: str
    name: str


class UnscheduledCourseOut(BaseModel):
    assignment_id: int
    subject_name: str
    class_names: list[str] = []
    periods: int


# ── 自動排課任務(M3-4)────────────────
class AutoScheduleRequest(BaseModel):
    """timeout 預設 10 分鐘(architecture.md §3.3),可設定。"""

    max_seconds: int = Field(default=600, ge=10, le=3600)
    seed: int = Field(default=0, ge=0)
    # 部分排課:允許少數課務未排入,並可勾選放寬的硬約束(M3-5)
    allow_partial: bool = False
    relax: list[str] = []


class AutoScheduleAccepted(BaseModel):
    job_id: str


class SolveJobOut(BaseModel):
    job_id: str
    status: str  # queued / running / finished / failed / cancelled
    semester_id: int
    source_timetable_id: int
    source_name: str
    max_seconds: float
    elapsed: float
    solutions: int
    objective: float | None = None
    result_timetable_id: int | None = None
    result_name: str | None = None
    error: str | None = None
    report: SoftReportOut | None = None
    phase: str = "solving"  # solving / explaining
    partial: bool = False
    conflict: ConflictReportOut | None = None
    unscheduled: list[UnscheduledCourseOut] | None = None
