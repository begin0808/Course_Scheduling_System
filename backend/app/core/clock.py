"""學校時區的「現在/今天」與「節次是否已上過」判定(config.tz,見 architecture.md D6)。

「已完成」不落盤成狀態,而是**讀取時推導**:一個受影響節次是否已經上過,由它的日期
與節次結束時間對照學校時區的現在決定。銷假不得抹除已上過的課(鐘點照算)、已上過的
處置不得再變更——兩道完整性關口都問這裡,不依賴任何排程器。
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings


def school_now() -> datetime:
    return datetime.now(ZoneInfo(settings.tz))


def school_today() -> date:
    return school_now().date()


def is_past_slot(day: date, end_time: time | None) -> bool:
    """該節次相對學校時區的現在是否已經上過(結束)。

    當天以節次結束時間判定;節次表沒填結束時間時保守視為尚未結束
    (整天內仍允許處置,與 leaves.expand 的保守策略一致)。
    """
    now = school_now()
    today = now.date()
    if day < today:
        return True
    if day > today:
        return False
    if end_time is None:
        return False
    return now.time() >= end_time
