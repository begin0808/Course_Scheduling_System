"""基礎資料(教師/科目/場地/班級)schema。"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType


# ── 科目 ──────────────────────────────
class SubjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    domain: str | None = Field(default=None, max_length=64)
    required_room_type: RoomType | None = None
    default_block_size: int = Field(default=1, ge=1, le=8)


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int


# ── 教師 ──────────────────────────────
class TeacherIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    base_periods: int = Field(default=0, ge=0)
    admin_title: str | None = Field(default=None, max_length=32)
    admin_reduction: int = Field(default=0, ge=0)
    is_external: bool = False
    is_active: bool = True
    subject_ids: list[int] = []


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    base_periods: int
    admin_title: str | None
    admin_reduction: int
    is_external: bool
    is_active: bool
    subjects: list[SubjectBrief] = []


class TeacherTimeRuleIn(BaseModel):
    weekday: int = Field(ge=1, le=6)
    period_no: int = Field(ge=1)
    rule_type: TeacherRuleType


class TeacherTimeRuleOut(TeacherTimeRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ── 場地 ──────────────────────────────
class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    room_type: RoomType = RoomType.normal
    capacity: int | None = Field(default=None, ge=0)
    subject_ids: list[int] = []


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    room_type: RoomType
    capacity: int | None
    subjects: list[SubjectBrief] = []


# ── 班級 ──────────────────────────────
class ClassUnitIn(BaseModel):
    grade: int = Field(ge=1, le=12)
    name: str = Field(min_length=1, max_length=32)
    track: ClassTrack
    department: str | None = Field(default=None, max_length=32)
    student_count: int | None = Field(default=None, ge=0)
    homeroom_teacher_id: int | None = None


class ClassUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    grade: int
    name: str
    track: ClassTrack
    department: str | None
    student_count: int | None
    homeroom_teacher_id: int | None
    homeroom_teacher: SubjectBrief | None = None  # 借用 {id,name} 結構顯示導師
