"""排課約束設定(architecture.md §3.2 軟約束權重與可調參數)。

以 key/value 存放而非固定欄位:軟約束會隨版本增減,加一條約束不該要一次遷移。
未設定的 key 一律回退 `app.solver.problem.SolverConfig` 的預設值。
權重 0 = 關閉該項軟約束。設定 UI 於 v2 才做(tasks.md M3-3)。
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConstraintConfig(Base):
    __tablename__ = "constraint_configs"
    __table_args__ = (
        UniqueConstraint("semester_id", "key", name="uq_constraint_configs_semester_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[int] = mapped_column(Integer)
