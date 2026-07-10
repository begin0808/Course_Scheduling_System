"""請假與受影響節次 schema(M4-1)。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class AffectedPeriodOut(BaseModel):
    id: int
    date: date
    weekday: int
    period_no: int
    period_name: str  # 「第三節」——一律用節次表的名稱,不用內部 period_no
    start_time: time | None = None
    end_time: time | None = None
    subject_name: str
    class_names: str
    room_name: str
    status: str  # pending / resolved / completed / cancelled
    handler_teacher_id: int | None = None
    handler_name: str | None = None

    model_config = {"from_attributes": True}


class LeaveRequestIn(BaseModel):
    """時間為空 = 該端點整天。單日 + 起訖時間 = 半天假。"""

    teacher_id: int | None = None  # 組長代登時指定;教師自登留空
    leave_type: str
    start_date: date
    start_time: time | None = None
    end_date: date
    end_time: time | None = None
    reason: str = Field(default="", max_length=200)


class LeaveRequestOut(BaseModel):
    id: int
    semester_id: int
    teacher_id: int
    teacher_name: str
    leave_type: str
    leave_type_label: str
    start_date: date
    start_time: time | None = None
    end_date: date
    end_time: time | None = None
    reason: str
    status: str
    created_by_name: str
    created_at: datetime
    affected_count: int = 0
    pending_count: int = 0
    affected_periods: list[AffectedPeriodOut] = []


class LeaveCancelled(BaseModel):
    id: int
    status: str
    revoked_count: int  # 原本已指派、現在被取消的節次數
    notified_teachers: list[str] = []


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    link: str
    created_at: datetime
    read_at: datetime | None = None
    acknowledged_at: datetime | None = None

    model_config = {"from_attributes": True}
