"""學期 model。

同校可並存多學期(準備中/進行中/已封存),所有資料以 semester_id 為範圍(見 D3/D5)。
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.period import PeriodTable


class SemesterStatus(enum.StrEnum):
    preparing = "preparing"  # 準備中(建置資料、排課)
    active = "active"        # 進行中(課表已發布、日常調代課)
    archived = "archived"    # 已封存(歷史保存)


class Semester(Base):
    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("academic_year", "term", name="uq_semesters_academic_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[int] = mapped_column(Integer)  # 學年度,如 115
    term: Mapped[int] = mapped_column(Integer)           # 學期,1 或 2
    # 領域日期,無時區(見 architecture.md D6)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SemesterStatus.preparing.value)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    period_tables: Mapped[list["PeriodTable"]] = relationship(
        back_populates="semester", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def label(self) -> str:
        return f"{self.academic_year} 學年度第 {self.term} 學期"
