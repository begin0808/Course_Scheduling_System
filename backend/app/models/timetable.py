"""課表版本與格位 model。

Timetable:同學期可多份草稿(draft)並存,僅一份 published(見 architecture.md D4)。
ScheduleEntry:一筆配課排入的格位(weekday × period_no,span 表連堂佔用節數)。
跑班群組的多筆配課同時排在同一時段(H7),以「同 scheduling_unit 的多筆 entry」表達。
唯一性(教師/班級/場地同時段不重複)由 conflict_checker 於應用層驗證,不設 DB 約束
(跨節次表以牆鐘時間判定,非單純欄位唯一性,見 architecture.md D7)。
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.assignment import CourseAssignment
from app.models.basedata import Room


class TimetableStatus(enum.StrEnum):
    draft = "draft"          # 草稿(可多份)
    published = "published"  # 已發布(同學期至多一份)
    archived = "archived"    # 已封存


class Timetable(Base):
    __tablename__ = "timetables"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=TimetableStatus.draft.value)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 刻意用預設 lazy(select):課表可能有數千格,取 Timetable 本身時不應連帶載入全部格位
    # (check-conflict 為拖曳熱路徑)。需要格位時由呼叫端明確查詢 ScheduleEntry。
    entries: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates="timetable", cascade="all, delete-orphan"
    )


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[int] = mapped_column(
        ForeignKey("timetables.id", ondelete="CASCADE"), index=True
    )
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    period_no: Mapped[int] = mapped_column(Integer)  # 連堂時為起始節次
    span: Mapped[int] = mapped_column(Integer, default=1)  # 佔用連續節數(連堂 >1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # H9 鎖定不得移動
    # 本格位實際使用的場地;空 = 沿用配課的 room_id。
    # 排課引擎對「只指定場地類型」的配課逐格挑教室,結果存這裡;調代課的教室異動亦然。
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )

    timetable: Mapped[Timetable] = relationship(back_populates="entries")
    assignment: Mapped[CourseAssignment] = relationship(lazy="selectin")
    room: Mapped[Room | None] = relationship(lazy="selectin")

    @property
    def effective_room_id(self) -> int | None:
        """格位場地優先,未指定則沿用配課場地。"""
        return self.room_id if self.room_id is not None else self.assignment.room_id
