"""請假與受影響節次 model(architecture.md §5.3 狀態機)。

**這裡是「週循環格」與「特定日期」的交界。** M0–M3 的一切都建立在
`(weekday, period_no)` 的週循環抽象上;請假卻是「王師 11/12 上午請假」這種特定日期的事實。
`affected_period` 就是把前者依日曆展開成後者的產物,M4 之後的代課推薦、今日看板、
鐘點統計全部長在它上面。

**它是快照,不是 join。** 展開的當下把配課、教師、班級、場地、節次名稱與起訖時間一併寫死。
理由與 D4(已發布課表是不可變快照)一致:課表可以重新發布,但「王師 11/12 第三節
原本要上 301 班的國文」是一件已經發生的歷史事實,不該隨著課表改版而漂移——
更不該讓一筆已經指派出去的代課,隔天指向另一門課。
"""

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import Teacher


class LeaveType(enum.StrEnum):
    official = "official"        # 公假
    personal = "personal"        # 事假
    sick = "sick"                # 病假
    marriage = "marriage"        # 婚假
    bereavement = "bereavement"  # 喪假
    maternity = "maternity"      # 產假
    training = "training"        # 進修


# 以字串為 key:資料庫存的是 leave_type 欄位的值,查表時不必先轉回 enum
LEAVE_TYPE_CN: dict[str, str] = {
    LeaveType.official.value: "公假",
    LeaveType.personal.value: "事假",
    LeaveType.sick.value: "病假",
    LeaveType.marriage.value: "婚假",
    LeaveType.bereavement.value: "喪假",
    LeaveType.maternity.value: "產假",
    LeaveType.training.value: "進修",
}


class LeaveStatus(enum.StrEnum):
    registered = "registered"  # 已登記(受影響節次已展開)
    cancelled = "cancelled"    # 已銷假(所有處置級聯取消)


class AffectedStatus(enum.StrEnum):
    """architecture.md §5.3:待處理 → 已確認 → 已完成;任一階段皆可因銷假轉為已取消。"""

    pending = "pending"      # 待處理
    resolved = "resolved"    # 已確認(已指派代課/調課/併班/自習/不處理)
    completed = "completed"  # 已完成(上課日結束)
    cancelled = "cancelled"  # 已取消(銷假)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    leave_type: Mapped[str] = mapped_column(String(20))
    # 領域日期/時間,無時區(architecture.md D6)。時間為空 = 該端點整天。
    start_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=LeaveStatus.registered.value)

    # 登記人(教師自登或組長代登);帳號刪除後仍保留姓名快照
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str] = mapped_column(String(64), default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teacher: Mapped[Teacher] = relationship(lazy="selectin")
    affected_periods: Mapped[list["AffectedPeriod"]] = relationship(
        back_populates="leave_request", cascade="all, delete-orphan", lazy="selectin",
    )

    @property
    def is_half_day(self) -> bool:
        return self.start_time is not None or self.end_time is not None


class AffectedPeriod(Base):
    __tablename__ = "affected_periods"
    __table_args__ = (
        # 同一張假單、同一天、同一節課只會出現一次
        UniqueConstraint(
            "leave_request_id", "date", "period_no", "class_names",
            name="uq_affected_periods_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    leave_request_id: Mapped[int] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="CASCADE"), index=True
    )
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )

    date: Mapped[date] = mapped_column(Date, index=True)  # 實際上課日
    weekday: Mapped[int] = mapped_column(Integer)
    period_no: Mapped[int] = mapped_column(Integer)

    # ── 快照欄位(展開當下的事實,不隨課表改版而變)──
    period_name: Mapped[str] = mapped_column(String(32), default="")  # 「第三節」,不用 period_no
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    subject_name: Mapped[str] = mapped_column(String(64), default="")
    class_names: Mapped[str] = mapped_column(String(128), default="")  # 跑班群組可能多班
    room_name: Mapped[str] = mapped_column(String(64), default="")

    # 溯源用;課表被刪除或重新發布時設為 NULL,快照欄位仍在
    schedule_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_entries.id", ondelete="SET NULL"), nullable=True
    )
    course_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(20), default=AffectedStatus.pending.value)
    # 已指派的處理人(代課教師)。M4-2 的 `substitution` 才是處置方式的真相來源
    # (代課/調課/併班/自習/不處理、是否計鐘點、經費來源);這裡刻意冗餘一個指標,
    # 供銷假級聯通知、今日看板與月結統計直接查詢,不必每次回頭 join。
    handler_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    leave_request: Mapped[LeaveRequest] = relationship(back_populates="affected_periods")
    handler: Mapped[Teacher | None] = relationship(lazy="selectin")
