"""調代課處置 model(M4-2,architecture.md §5.3)。

一筆 `substitution` = 對一個受影響節次的處置決定。**指派即生效**——沒有邀請/婉拒流程
(2026-07-09 定案:組長實務上已事先口頭徵得同意,通知僅為正式告知)。

處置方式的真相在這裡;`affected_period.handler_teacher_id` / `.status` 只是冗餘指標,
供今日看板、月結統計直接查詢,不必每次回頭 join。一個受影響節次至多一筆有效處置
(改派時更新同一筆),故 `affected_period_id` 唯一。

**swap(調課)的語意**:甲請假日的某節由乙代;交換條件是甲之後補乙一節(乙原本那節放掉)。
因此要驗四件事都無衝突:乙在甲那節、甲在乙那節、以及兩個班各自不重複排課。
`swap_*` 欄位記錄「乙原本要放掉、改由甲補」的那一節(以快照保存,課表改版不影響已成立的調課)。
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import Teacher


class SubstitutionType(enum.StrEnum):
    substitute = "substitute"    # 代課(找人代)
    swap = "swap"                # 調課(兩位教師互換節次)
    merge = "merge"              # 併班(併入他班,不另計代課鐘點)
    self_study = "self_study"    # 自習(學生自習,不另計代課鐘點)
    cancel = "cancel"            # 不處理(當天停課/彈性運用)


SUBSTITUTION_TYPE_CN = {
    SubstitutionType.substitute.value: "代課",
    SubstitutionType.swap.value: "調課",
    SubstitutionType.merge.value: "併班",
    SubstitutionType.self_study.value: "自習",
    SubstitutionType.cancel.value: "不處理",
}

# 需要指定一位「處理教師」的處置(代課的代課老師、調課的對調老師、併班的接收老師)
TYPES_WITH_HANDLER = frozenset({
    SubstitutionType.substitute.value,
    SubstitutionType.swap.value,
    SubstitutionType.merge.value,
})


class Substitution(Base):
    __tablename__ = "substitutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    # 一個受影響節次至多一筆有效處置;改派時更新同一筆
    affected_period_id: Mapped[int] = mapped_column(
        ForeignKey("affected_periods.id", ondelete="CASCADE"), unique=True, index=True
    )
    type: Mapped[str] = mapped_column(String(20))

    # 處理教師:代課/調課/併班的接手者;自習/不處理為空
    handler_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 是否計代課鐘點:代課通常計;併班/自習/不處理不計(architecture.md §5.4 月結)
    counts_toward_hours: Mapped[bool] = mapped_column(Boolean, default=True)
    funding_source: Mapped[str] = mapped_column(String(32), default="")  # 經費來源標記(選填)

    # ── 調課的交換節次(乙原本要放掉、改由甲補的那一節)──
    # 以快照保存:課表改版不影響已成立的調課
    swap_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    swap_period_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swap_period_name: Mapped[str] = mapped_column(String(32), default="")
    swap_class_names: Mapped[str] = mapped_column(String(128), default="")
    swap_subject_name: Mapped[str] = mapped_column(String(64), default="")
    swap_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_entries.id", ondelete="SET NULL"), nullable=True
    )

    note: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    handler: Mapped[Teacher | None] = relationship(lazy="selectin")
