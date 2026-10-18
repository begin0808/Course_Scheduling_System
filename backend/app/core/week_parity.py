"""單週/雙週的判定(v1.3.0)。實作在 `app.solver.week_parity`。

排課引擎(`app.solver`)只能引用自己的套件(見 tests/solver/test_purity.py),
所以判定邏輯放在引擎那邊,這裡轉出給服務層使用。
"""

from app.solver.week_parity import (
    EVEN,
    ODD,
    PARITIES,
    PARITY_CN,
    PARITY_SHORT,
    fmt_periods,
    overlaps,
    runs_in_week,
    week_number,
    week_parity,
    weekly_load,
)

__all__ = [
    "EVEN", "ODD", "PARITIES", "PARITY_CN", "PARITY_SHORT", "fmt_periods", "overlaps",
    "runs_in_week", "week_number", "week_parity", "weekly_load",
]
