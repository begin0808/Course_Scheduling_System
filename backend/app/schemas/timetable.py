"""課表(timetable / schedule_entry)與衝突檢查 schema。"""

from datetime import time

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
    # id 供前端三視角精確篩選(姓名/班名可能重複,不可當鍵)
    teacher_ids: list[int] = []
    class_ids: list[int] = []
    room_id: int | None = None


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
    # 發布後回填:今日之後、依舊課表展開的受影響節次數(>0 提醒組長重新檢視調代課)
    stale_affected: int = 0


class ConflictOut(BaseModel):
    code: str
    message: str


class CheckRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)
    ignore_entry_id: int | None = None  # 移動既有格位時,忽略自身
    room_id: int | None = None  # 本格位使用的場地(空=沿用配課場地)


class CheckResponse(BaseModel):
    ok: bool
    conflicts: list[ConflictOut] = []


class PlaceRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)
    room_id: int | None = None  # 本格位使用的場地(空=沿用配課場地)


class MoveRequest(BaseModel):
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)


# ── 版本管理與發布 ────────────────────
class TimetableRename(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class UnplacedItem(BaseModel):
    course_assignment_id: int
    subject: str
    classes: list[str] = []
    teachers: list[str] = []
    required: int
    placed: int
    remaining: int
    # 自動排課當時 solver 說的「為什麼排不下」(手動未排完則為空,M6-3)
    reason: str = ""


class CompletenessOut(BaseModel):
    required: int
    placed: int
    remaining: int
    complete: bool
    unplaced: list[UnplacedItem] = []


# ── 全員唯讀課表查詢 ──────────────────
class PublicSemester(BaseModel):
    id: int
    label: str


class NamedBrief(BaseModel):
    id: int
    name: str


class PublicClass(BaseModel):
    id: int
    name: str
    grade: int
    period_table_id: int | None = None


class PublicPeriod(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weekday: int
    period_no: int
    name: str
    start_time: time | None = None
    end_time: time | None = None
    type: str


class PublicPeriodTable(BaseModel):
    id: int
    name: str
    num_weekdays: int
    is_default: bool
    periods: list[PublicPeriod] = []


class PublishedTimetableOut(BaseModel):
    """已發布課表 + 查詢頁所需的全部選項,一次回傳(教師端只打這一支)。"""

    id: int
    semester_id: int
    semester_label: str
    name: str
    status: str
    entries: list[ScheduleEntryOut] = []
    classes: list[PublicClass] = []
    teachers: list[NamedBrief] = []
    rooms: list[NamedBrief] = []
    period_tables: list[PublicPeriodTable] = []
