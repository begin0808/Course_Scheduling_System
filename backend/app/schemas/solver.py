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
