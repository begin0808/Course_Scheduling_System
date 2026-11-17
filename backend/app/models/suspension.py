"""停課日 model(v1.4.19)。

組長回報:「停課日在哪邊可以設定?」——校慶補假、颱風假、段考下午、某個年級的戶外教學、
特定班級的探索活動,這些時段那幾個班不上課。系統原本只有請假時的「不處理(當天停課)」,
那只管請假老師的那一節,不知道全校或整個班停課。

一筆停課 = 一段日期 × 對象(全校,或指定班級)× 範圍(整天,或第幾節到第幾節)。
「第幾節」只數一般課(與調課單、巡堂表相同),各班依自己的節次表對應,國中小兩部作息
不同也各自對得上。指定年級在畫面上是「一次勾選整個年級的班」,存的仍是班級。

停課的課:
- 請假時不列為受影響節次(那節本來就不上課,不必找人代);整天停課的班也不必代導。
- 找調課補課節次時,停課的那一節不能拿來補課。
- 巡堂表、週課表、教師週總表、即時概況標「停課」;全校整天停課的日子巡堂表略過。

判斷規則集中在 `app.services.suspensions`。
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import ClassUnit

suspension_classes = Table(
    "class_suspension_classes",
    Base.metadata,
    Column("suspension_id", ForeignKey("class_suspensions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("class_unit_id", ForeignKey("class_units.id", ondelete="CASCADE"),
           primary_key=True, index=True),
)


class ClassSuspension(Base):
    __tablename__ = "class_suspensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    whole_school: Mapped[bool] = mapped_column(Boolean, default=True)
    # 第幾節到第幾節(只數一般課,含頭尾);兩個都空 = 整天
    from_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(64), default="")
    created_by_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    classes: Mapped[list[ClassUnit]] = relationship(
        secondary=suspension_classes, lazy="selectin",
        order_by=[ClassUnit.grade, ClassUnit.name])

    @property
    def all_day(self) -> bool:
        return self.from_ordinal is None and self.to_ordinal is None
