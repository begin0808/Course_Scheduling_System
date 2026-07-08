"""設定精靈 schema。"""

from pydantic import BaseModel


class WizardStateOut(BaseModel):
    current_step: int
    completed: bool
    semester_id: int | None
    total_steps: int
    has_semesters: bool  # 系統是否已有任何學期(輔助前端判斷是否需引導)


class WizardStateUpdate(BaseModel):
    current_step: int | None = None
    completed: bool | None = None
    semester_id: int | None = None


class SemesterSummary(BaseModel):
    subjects: int
    teachers: int
    classes: int
    rooms: int
