"""基礎資料(教師/科目/場地/班級)schema。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validators import is_valid_email
from app.models.basedata import ClassTrack, RoomType, TeacherRuleType


def _normalize_optional_email(value: str | None) -> str | None:
    """空字串轉 None;非空則驗證 Email 格式。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not is_valid_email(value):
        raise ValueError("Email 格式不正確")
    return value


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
    is_major: bool = False  # 主科(排課引擎 S5:盡量排上午)


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int


# ── 教師 ──────────────────────────────
class TeacherIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    id_last4: str | None = Field(default=None, max_length=4)
    base_periods: int = Field(default=0, ge=0)
    admin_title: str | None = Field(default=None, max_length=32)
    admin_reduction: int = Field(default=0, ge=0)
    is_external: bool = False
    is_active: bool = True
    subject_ids: list[int] = []
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    line_id: str | None = Field(default=None, max_length=64)
    user_id: int | None = None  # 綁定的登入帳號(空=不綁定)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    id_last4: str | None
    base_periods: int
    admin_title: str | None
    admin_reduction: int
    is_external: bool
    is_active: bool
    subjects: list[SubjectBrief] = []
    email: str | None = None
    phone: str | None = None
    line_id: str | None = None
    user_id: int | None = None


class BindableAccount(BaseModel):
    """可供教師綁定的帳號(teacher 角色、於本學期尚未被綁定者)。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str


class TeacherAccountIn(BaseModel):
    """為既有教師補開登入帳號(匯入時沒勾、或後來才需要用系統的老師)。"""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(default="", max_length=128)  # 空=用部署設定的預設密碼


class ResetPasswordIn(BaseModel):
    password: str = Field(default="", max_length=128)  # 空=用部署設定的預設密碼


class TeacherAccountOut(BaseModel):
    """教師的登入帳號狀態(給畫面顯示;不含密碼)。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    must_change_password: bool
    is_active: bool = True  # 停用後無法登入,帳號與歷史資料仍保留


class AccountActiveIn(BaseModel):
    is_active: bool


class TeacherDeleteImpact(BaseModel):
    """刪除教師會連帶消失的東西(刪除前先讓使用者看清楚)。"""

    teacher_id: int
    teacher_name: str
    leave_requests: int        # 請假單數
    substitutions: int         # 調代課處置數(含代課、調課、併班…)
    assignments: int           # 會失去這位教師的配課數
    homeroom_classes: int      # 擔任導師的班級數(有的話根本不能刪)
    account_username: str = ""  # 綁定的登入帳號(刪除教師時會一併停用)


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
    period_table_id: int | None = None  # 空=用學期預設節次表


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
    period_table_id: int | None = None
