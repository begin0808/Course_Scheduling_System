"""課表(timetable / schedule_entry)與衝突檢查 schema。"""

from pydantic import BaseModel, ConfigDict, Field


class TimetableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ScheduleEntryOut(BaseModel):
    id: int
    course_assignment_id: int
    weekday: int
    period_no: int
    span: int
    locked: bool
    subject: str
    teachers: list[str] = []
    classes: list[str] = []
    unit_type: str
    unit_name: str
    room: str | None = None


class TimetableBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    status: str
    entry_count: int = 0


class TimetableOut(BaseModel):
    id: int
    semester_id: int
    name: str
    status: str
    entries: list[ScheduleEntryOut] = []


class ConflictOut(BaseModel):
    code: str
    message: str


class CheckRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)
    ignore_entry_id: int | None = None  # 移動既有格位時,忽略自身


class CheckResponse(BaseModel):
    ok: bool
    conflicts: list[ConflictOut] = []


class PlaceRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)


class MoveRequest(BaseModel):
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
