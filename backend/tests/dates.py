"""測試用的日期基準:一律由「執行當日」推算,不硬編。

**為什麼不能硬編未來日期**:`clock.is_past_slot` 以真實時鐘判定節次是否已上過。
日期一旦成為過去,代課指派會被 409 拒絕、銷假不再級聯——整套測試在某個沒人動過
程式碼的早晨無聲轉紅(原本埋的引信是 2026-11-11)。

用法:`from tests.dates import SEM_START, SEM_END, WED`。星期採 ISO(1=週一 … 7=週日),
與 `ScheduleEntry.weekday` 及 `leaves.expand` 的 `isoweekday()` 同一套。
"""

from datetime import date, timedelta

# 基準週距今的最小天數。取 14 天的理由:
#   1. 基準週的每一節都必須還沒上過——若取「今天」,下午跑測試時上午的節次已過期。
#   2. 有測試會往前一週找日子,前一週也必須仍在未來。
LEAD_DAYS = 14

# 學期起訖相對基準週留的緩衝(要能容下 CROSS_WED2 這種往後數週的日子)。
_SEM_LEAD = timedelta(days=30)
_SEM_TAIL = timedelta(days=60)


def on_or_after(weekday: int, day: date) -> date:
    """`day` 當天或之後、最近的指定 ISO 星期(1=週一 … 7=週日)。"""
    if not 1 <= weekday <= 7:
        raise ValueError(f"weekday 需為 1~7(ISO),得到 {weekday}")
    return day + timedelta(days=(weekday - day.isoweekday()) % 7)


def base_monday(today: date | None = None) -> date:
    """基準測試週的週一:距今至少 `LEAD_DAYS` 天,且該週一到「下週三」落在同一個月。

    同月是硬需求,不是美觀:代課推薦的公平計數與月結統計都以「受影響節次那一天的月份」
    為範圍(`_monthly_sub_counts`)。若 WED 與 WED2 跨月,「林師本月已代 1 節」在 WED2
    那個月會歸零,「本月代課少者優先」就驗不到。跨月的案例另由 `cross_month_wednesday` 負責。
    """
    mon = on_or_after(1, (today or date.today()) + timedelta(days=LEAD_DAYS))
    for _ in range(6):
        if (mon + timedelta(days=9)).month == mon.month:  # +9 天 = 下週三
            return mon
        mon += timedelta(days=7)
    raise AssertionError("六週內必有一個「當週到下週三同月」的週一")  # pragma: no cover


def cross_month_wednesday(today: date | None = None) -> date:
    """一個週三,且「下一個週三」落在不同月份(供跨月假單拆帳測試)。

    任何連續 5 週內必有一個月底的週三,故有限次即可找到。
    """
    wed = on_or_after(3, base_monday(today))
    for _ in range(6):
        if (wed + timedelta(days=7)).month != wed.month:
            return wed
        wed += timedelta(days=7)
    raise AssertionError("六週內必有跨月的週三,推算邏輯有誤")  # pragma: no cover


MON = base_monday()
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)
THU = MON + timedelta(days=3)
FRI = MON + timedelta(days=4)
SAT = MON + timedelta(days=5)
SUN = MON + timedelta(days=6)
NEXT_MON = MON + timedelta(days=7)
WED2 = WED + timedelta(days=7)  # 下週三(swap 補課、跨週統計用)

# 跨月的兩個週三(11/25 與 12/02 那組硬編日期的動態版)
CROSS_WED = cross_month_wednesday()
CROSS_WED2 = CROSS_WED + timedelta(days=7)

# 學期起訖:包住上面所有日子,前後各留緩衝供「學期外」的邊界測試
SEM_START = MON - _SEM_LEAD
SEM_END = max(WED2, CROSS_WED2) + _SEM_TAIL
BEFORE_SEM = SEM_START - timedelta(days=1)
AFTER_SEM = SEM_END + timedelta(days=1)
