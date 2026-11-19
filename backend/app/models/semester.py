"""學期 model。

同校可並存多學期(準備中/進行中/已封存),所有資料以 semester_id 為範圍(見 D3/D5)。
"""

import enum
from collections.abc import Sequence
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


# 學期類型(term 欄)。3、4 是 v1.4.22 的寒暑假輔導:日期必填、不能和其他學期重疊、
# 不管基本鐘點與超鐘點(上幾節給幾節)。沿用 term 欄,(學年度, term) 一樣不能重複。
TERM_WINTER = 3  # 寒假輔導
TERM_SUMMER = 4  # 暑期輔導
TUTORING_TERMS = frozenset({TERM_WINTER, TERM_SUMMER})
TERM_NAMES = {1: "第 1 學期", 2: "第 2 學期", TERM_WINTER: "寒假輔導", TERM_SUMMER: "暑期輔導"}


def approx_start(academic_year: int, term: int) -> date:
    """沒填起訖日期時,用學年度推估開始日,只拿來排序(民國學年度從 8 月開始)。"""
    ad = academic_year + 1911
    return {
        1: date(ad, 8, 1), 2: date(ad + 1, 2, 1),
        TERM_WINTER: date(ad + 1, 1, 20), TERM_SUMMER: date(ad + 1, 7, 1),
    }.get(term, date(ad, 8, 1))


class Semester(Base):
    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("academic_year", "term", name="uq_semesters_academic_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[int] = mapped_column(Integer)  # 學年度,如 115
    term: Mapped[int] = mapped_column(Integer)           # 1、2 學期;3 寒假輔導、4 暑期輔導
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
    def is_tutoring(self) -> bool:
        """寒暑假輔導(v1.4.22)。"""
        return self.term in TUTORING_TERMS

    @property
    def label(self) -> str:
        if self.is_tutoring:
            return f"{self.academic_year} 學年度{TERM_NAMES[self.term]}"
        return f"{self.academic_year} 學年度第 {self.term} 學期"

    @property
    def sort_date(self) -> date:
        """學期清單由新到舊的排序依據:有開始日用開始日,否則用學年度推估。"""
        return self.start_date or approx_start(self.academic_year, self.term)


def sorted_semesters(rows: Sequence[Semester]) -> list[Semester]:
    """由新到舊:有開始日用開始日,否則用學年度推估(寒假輔導排在同學年上下學期之間)。"""
    return sorted(rows, key=lambda x: (x.sort_date, x.id), reverse=True)
