"""單週/雙週的判定(v1.3.0)。

規則(使用者定案):**學期開始那一週是第 1 週 = 單週**,之後每週固定輪流,放假、段考
都不調整。週以週一為起點,所以學期若從週三開始,那一週仍是第 1 週。

配課的 `week_parity`:None = 每週都上;"odd" = 只上單週;"even" = 只上雙週。

這個模組不碰資料庫;服務層請由 `app.core.week_parity` 引用。
"""

from datetime import date, timedelta

ODD = "odd"
EVEN = "even"
PARITIES = (ODD, EVEN)
PARITY_CN = {ODD: "單週", EVEN: "雙週"}
PARITY_SHORT = {ODD: "單", EVEN: "雙"}


def week_parity(semester_start: date | None, day: date) -> str | None:
    """day 是單週還是雙週;學期沒有開始日期時無從判斷,回 None(視為每週都適用)。"""
    if semester_start is None:
        return None
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    week_index = (day - first_monday).days // 7  # 第 1 週 = 0
    return ODD if week_index % 2 == 0 else EVEN


def week_number(semester_start: date | None, day: date) -> int | None:
    """第幾週(從 1 起算);學期開始前回 0 或負數。"""
    if semester_start is None:
        return None
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    return (day - first_monday).days // 7 + 1


def runs_in_week(lesson_parity: str | None, week: str | None) -> bool:
    """這堂課在這一週有沒有上:每週的課一定有;單雙週的課只在對應的那一週。"""
    return lesson_parity is None or week is None or lesson_parity == week


def overlaps(a: str | None, b: str | None) -> bool:
    """兩堂課會不會在同一週碰在一起:單週的課和雙週的課永遠不會。"""
    return a is None or b is None or a == b


def weekly_load(periods_per_week: int, parity: str | None) -> float:
    """平均每週的節數:隔週的課算一半(使用者定案:鐘點按實際上課量)。"""
    return periods_per_week / 2 if parity else float(periods_per_week)


def fmt_periods(n: float) -> str:
    """鐘點顯示:整數不帶小數(20),半節帶一位(20.5)。"""
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"
