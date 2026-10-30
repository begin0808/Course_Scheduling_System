"""請假與受影響節次 schema(M4-1)。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field

# 欄位名 date 會遮蔽同名型別(mypy 判為變數),其後的欄位以別名標註
_Date = date


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
    # 已經過去、還沒處理:畫面標「待補登」,補登不通知、不能調課(v1.4.2)
    is_past: bool = False
    handler_teacher_id: int | None = None
    handler_name: str | None = None
    sub_type: str | None = None  # 已處置時的處置方式(substitute/swap/…),未處置為空
    # 調課才有:請假教師回來補課的那一節(讓清單直接寫出「王師 10/8 第二節補課」)
    swap_date: _Date | None = None
    swap_period_name: str = ""

    model_config = {"from_attributes": True}


class HomeroomCoverOut(BaseModel):
    """代導(v1.4.0):請假的導師帶的班,某一天由誰代導。"""

    id: int
    date: date
    weekday: int
    class_name: str
    part_label: str          # 全天 / 上午 / 下午 / 10:00~14:00
    is_half_day: bool
    status: str              # pending / resolved / completed / cancelled
    no_cover: bool           # 已確認「不需代導」
    is_past: bool = False    # 那天已經過了(還沒安排的話就是待補登,v1.4.2)
    handler_teacher_id: int | None = None
    handler_name: str | None = None


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
    homeroom_covers: list[HomeroomCoverOut] = []
    cover_pending_count: int = 0  # 還沒安排的代導(天次)


class LeaveCancelled(BaseModel):
    id: int
    status: str
    revoked_count: int  # 原本已指派、現在被取消的節次數
    revoked_cover_count: int = 0  # 原本已安排、現在被取消的代導(天次)
    notified_teachers: list[str] = []

