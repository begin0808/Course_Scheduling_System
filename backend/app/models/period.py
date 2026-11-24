"""節次表與節次 model。

一個學期可有多套節次表(完全中學:高中部/國中部各一套)。
節次表是 weekday × period_no 的格狀結構,每格(Period)有類型;
只有 `regular`(一般課)類型的格位參與排課(見 architecture.md H5)。
"""

import enum
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.semester import Semester


class PeriodType(enum.StrEnum):
    regular = "regular"      # 一般課(唯一參與排課者)
    morning = "morning"      # 早自習
    lunch = "lunch"          # 午休
    homeroom = "homeroom"    # 導師時間
    reserved = "reserved"    # 固定用途(週會/社團/彈性學習,不排課)


class PeriodTable(Base):
    __tablename__ = "period_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    num_weekdays: Mapped[int] = mapped_column(Integer, default=5)  # 一週上課天數(5 或 6)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    semester: Mapped["Semester"] = relationship(back_populates="period_tables")
    # 一律依星期、節次排序(v1.5.0):沒指定時資料庫回傳順序不保證,
    # 節次被修改過之後可能變成「第二節、第三節……第一節」
    periods: Mapped[list["Period"]] = relationship(
        back_populates="period_table", cascade="all, delete-orphan", lazy="selectin",
        order_by="(Period.weekday, Period.period_no)",
    )


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("period_table_id", "weekday", "period_no", name="uq_periods_cell"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period_table_id: Mapped[int] = mapped_column(
        ForeignKey("period_tables.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)   # 1=週一 … 5/6
    period_no: Mapped[int] = mapped_column(Integer)  # 當日節次順序(含休息時段),1..N
    name: Mapped[str] = mapped_column(String(32))    # 顯示名稱,如「第一節」「午休」
    # 領域時間(學校牆鐘時間),無時區(見 architecture.md D6)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    type: Mapped[str] = mapped_column(String(20), default=PeriodType.regular.value)

    period_table: Mapped["PeriodTable"] = relationship(back_populates="periods")
