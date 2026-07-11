"""三套學制驗證資料集(tasks.md 測試策略總則第 1 點,全案共用)。

- `build_elementary_small`   國小 6 班(包班+科任、週三下午空、導師時間)
- `build_junior_high_mid`    國中 12 班(領域課程+彈性課程+兼行政減課教師)
- `build_vocational_high`    技高 15 班 3 科(3 連堂實習+工場+業界師資+跑班群組)

三套資料皆已於 `tests/test_fixtures.py` 驗證自洽(無超鐘點、班級節數不超可排格數、
場地需求不超供給、跑班群組成員同節次表),可直接餵給 M3 排課引擎。
"""

from ._common import Builder, Fixture, room_demand, teacher_available_slots
from .elementary import build_elementary_small
from .junior_high import build_junior_high_mid
from .scale import build_large_school
from .vocational import build_vocational_high

__all__ = [
    "Builder",
    "Fixture",
    "build_elementary_small",
    "build_junior_high_mid",
    "build_large_school",
    "build_vocational_high",
    "room_demand",
    "teacher_available_slots",
]
