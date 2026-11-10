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
    # 代課的計費方式與是否計入鐘點(v1.4.4 起可事後修改,畫面要顯示目前的值)
    funding_source: str = ""
    counts_toward_hours: bool | None = None

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


class LeaveUpdateIn(BaseModel):
    """修改假單(v1.4.4):只能改假別與事由。

    日期、時間不能改——那會改變哪些節次受影響;登記錯日期請銷假重登。
    """

    leave_type: str | None = None
    reason: str | None = Field(default=None, max_length=200)


class SkippedPeriodOut(BaseModel):
    """登記請假時沒列入的一節:它已經在別張假單或「調課(未請假)」裡(v1.4.16)。"""

    date: date
    period_name: str
    taken_by: str


class DayPeriodOut(BaseModel):
    """這位老師這一天的一節課(新增調課時勾選,v1.4.5)。"""

    period_no: int
    period_name: str
    start_time: time | None = None
    end_time: time | None = None
    class_names: str
    subject_name: str
    is_past: bool          # 已經上過:選了就是補登調課(v1.4.10)
    taken_by: str = ""     # 已經在別張假單/調課裡:那張的假別名稱


class SwapRequestIn(BaseModel):
    """新增調課(未請假,v1.4.5):老師沒請假,只是要把這幾節和別人調。"""

    teacher_id: int
    date: date
    period_nos: list[int]
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
    # 只有登記時回傳:已經在別張假單或調課裡、這次沒列入的節次(v1.4.16)
    skipped: list[SkippedPeriodOut] = []


class LeaveCancelled(BaseModel):
    id: int
    status: str
    revoked_count: int  # 原本已指派、現在被取消的節次數
    revoked_cover_count: int = 0  # 原本已安排、現在被取消的代導(天次)
    notified_teachers: list[str] = []

