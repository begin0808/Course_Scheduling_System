"""設定精靈進度(單例)。

單校部署,全系統一份精靈狀態(id 固定為 1)。用於首次登入引導與續作。
"""

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SINGLETON_ID = 1
TOTAL_STEPS = 5


class WizardState(Base):
    __tablename__ = "wizard_state"

    id: Mapped[int] = mapped_column(primary_key=True)  # 固定為 1
    current_step: Mapped[int] = mapped_column(Integer, default=0)  # 0..TOTAL_STEPS-1
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 精靈過程中建立的學期(續作時沿用)
    semester_id: Mapped[int | None] = mapped_column(
        ForeignKey("semesters.id", ondelete="SET NULL"), nullable=True
    )
