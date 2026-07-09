"""配課(scheduling_unit / course_assignment)schema。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.basedata import RoomType
from app.schemas.basedata import SubjectBrief


# ── 排課單位(跑班群組)──────────────────
class ClassBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    grade: int


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    class_ids: list[int] = Field(min_length=2)  # 群組至少含 2 班


class SchedulingUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    unit_type: str
    name: str
    classes: list[ClassBrief] = []


# ── 配課教師 / 連堂 ───────────────────
class AssignmentTeacherIn(BaseModel):
    teacher_id: int
    is_lead: bool = True


class AssignmentTeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    teacher_id: int
    is_lead: bool
    name: str


class BlockRuleIn(BaseModel):
    block_size: int = Field(ge=2, le=4)
    count_per_week: int = Field(ge=1)


class BlockRuleOut(BlockRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ── 配課 ──────────────────────────────
class AssignmentIn(BaseModel):
    # 單班配課給 class_id;跑班群組配課給 scheduling_unit_id(擇一)
    class_id: int | None = None
    scheduling_unit_id: int | None = None
    subject_id: int
    periods_per_week: int = Field(ge=1, le=40)
    teachers: list[AssignmentTeacherIn] = Field(min_length=1)
    block_rules: list[BlockRuleIn] = []
    required_room_type: RoomType | None = None
    room_id: int | None = None
    lock_room: bool = False

    @model_validator(mode="after")
    def _check(self) -> "AssignmentIn":
        if (self.class_id is None) == (self.scheduling_unit_id is None):
            raise ValueError("請擇一提供 class_id(單班)或 scheduling_unit_id(跑班群組)")
        # 連堂總節數不可超過每週節數
        block_total = sum(b.block_size * b.count_per_week for b in self.block_rules)
        if block_total > self.periods_per_week:
            raise ValueError("連堂總節數超過每週節數")
        # 教師至多一位主教
        if sum(1 for t in self.teachers if t.is_lead) > 1:
            raise ValueError("至多一位主教教師")
        # 教師不可重複
        ids = [t.teacher_id for t in self.teachers]
        if len(ids) != len(set(ids)):
            raise ValueError("教師清單重複")
        return self


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    scheduling_unit: SchedulingUnitOut
    subject: SubjectBrief
    periods_per_week: int
    required_room_type: str | None
    room_id: int | None
    lock_room: bool
    teachers: list[AssignmentTeacherOut] = []
    block_rules: list[BlockRuleOut] = []


# ── 鐘點/負載統計 ─────────────────────
class TeacherLoad(BaseModel):
    teacher_id: int
    name: str
    base_periods: int
    admin_reduction: int
    target: int          # 應授節數 = base_periods - admin_reduction(不小於 0)
    assigned: int        # 已配課節數
    delta: int           # assigned - target(正=超鐘點,負=不足)


class ClassLoad(BaseModel):
    class_id: int
    name: str
    grade: int
    assigned: int        # 該班每週配課總節數
    capacity: int        # 可排節次數(regular slots)
    over_capacity: bool  # assigned > capacity
