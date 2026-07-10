"""排課引擎相關 schema(M3-1 pre-flight 報告)。"""

from pydantic import BaseModel


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
