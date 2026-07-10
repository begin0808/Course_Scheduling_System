"""操作軌跡 model(architecture.md §2.2 audit_log)。

誰在何時改了什麼。排課發布、調代課指派等關鍵異動必記;帳號被刪除時保留紀錄
(user_id 設為 NULL),避免軌跡消失。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(64), default="")  # 快照,帳號刪除後仍可辨識
    action: Mapped[str] = mapped_column(String(64), index=True)    # 如 publish_timetable
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
