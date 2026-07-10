"""通知 model(architecture.md §5.3)。

M4-1 只建立資料落地與寫入點;**寄送管道**(站內鈴鐺、Email、v2 的 webhook/LINE)
由 M4-3 以 `NotificationChannel` 介面實作。這裡先把「該通知誰、通知什麼」定下來,
因為銷假的級聯取消必須立刻能通知已被指派的代課教師——那是 M4-1 的驗收標準。

收件人以 `teacher_id` 表達而非 `user_id`:外聘師資可能沒有系統帳號但有 Email,
站內/Email 兩個管道各自從教師主檔解析(`teacher.user_id` / `teacher.email`)。
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import Teacher


class NotificationType(enum.StrEnum):
    leave_registered = "leave_registered"                # 請假已登記(組長代登時通知教師)
    leave_cancelled = "leave_cancelled"                  # 銷假
    substitution_assigned = "substitution_assigned"      # 被指派代課(M4-2)
    substitution_cancelled = "substitution_cancelled"    # 原訂代課取消(銷假級聯)
    timetable_published = "timetable_published"          # 課表發布(M4-3)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 「確認收到」:通知層的已讀確認,不影響課務狀態
    # (2026-07-09 定案:調代課不設邀請/婉拒流程,指派即生效)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    teacher: Mapped[Teacher | None] = relationship(lazy="selectin")
