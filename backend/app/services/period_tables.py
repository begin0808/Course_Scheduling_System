"""節次表解析與可排時段共用邏輯。

M2 起所有「某班/某節次表的合法時段」查詢一律經 resolve_period_table + regular_slots,
排課引擎不需關心學校是單一或多套節次表(混合學制封裝於此)。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit
from app.models.period import Period, PeriodTable, PeriodType


def semester_default_table(db: Session, semester_id: int) -> PeriodTable | None:
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id).order_by(PeriodTable.id)
    ).all()
    if not tables:
        return None
    return next((t for t in tables if t.is_default), tables[0])


def resolve_period_table(db: Session, class_unit: ClassUnit) -> PeriodTable | None:
    """班級所屬節次表:有指定則用之,否則回退學期預設表。"""
    if class_unit.period_table_id is not None:
        pt = db.get(PeriodTable, class_unit.period_table_id)
        if pt is not None:
            return pt
    return semester_default_table(db, class_unit.semester_id)


def regular_slots(db: Session, period_table_id: int) -> list[Period]:
    """節次表中可排課(type=regular)的格位,依星期、節次排序。"""
    return list(
        db.scalars(
            select(Period)
            .where(
                Period.period_table_id == period_table_id,
                Period.type == PeriodType.regular.value,
            )
            .order_by(Period.weekday, Period.period_no)
        ).all()
    )
