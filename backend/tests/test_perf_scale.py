"""M5-4 效能驗收(60 班規模):check-conflict 單格檢查 p95 < 100ms。

以 build_large_school(60) 建 60 班國中(660 配課、約 55 位教師),在課表塞入
接近整週滿排的格位量,量測衝突檢查的 p95。這是驗收②裡最硬性的一條數字。

「頁面載入 p95 < 2s」為前端量測(見 frontend/e2e 的 page-load 量測);「自動排課
< 10 分鐘」由 M3 的 junior_high < 60s 建模測試與 docker 實測共同保證(60 班求解耗時
於實機記錄,不放進 CI 單元測試以免每次跑十分鐘)。
"""

import time as _time

import pytest
from sqlalchemy import select

from app.models.period import Period, PeriodType
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.conflict_checker import check_conflict
from tests.fixtures import build_large_school


def _regular_slots(db, table_id):
    return list(db.scalars(
        select(Period).where(
            Period.period_table_id == table_id,
            Period.type == PeriodType.regular.value,
        ).order_by(Period.weekday, Period.period_no)
    ))


@pytest.mark.perf
def test_check_conflict_p95_under_100ms_at_60_classes(db):
    fx = build_large_school(db, num_classes=60)
    sid = fx.semester_id

    tt = Timetable(semester_id=sid, name="效能草稿", status=TimetableStatus.draft.value)
    db.add(tt)
    db.flush()

    # 以合法節次格位輪替塞滿:量測的是佔用索引的建立與比對速度,不要求教學合理。
    slots = _regular_slots(db, fx.table.id)
    assert slots, "節次表應有一般課格位"
    placed = 0
    for i, a in enumerate(fx.assignments):
        for k in range(a.periods_per_week):
            slot = slots[(i + k) % len(slots)]
            db.add(ScheduleEntry(
                timetable_id=tt.id, course_assignment_id=a.id,
                weekday=slot.weekday, period_no=slot.period_no, span=1,
                room_id=a.room_id, locked=False,
            ))
            placed += 1
    db.flush()
    assert placed > 1500, f"應塞入具規模的格位(實際 {placed})"

    probe = fx.assignments[0]
    slot = slots[len(slots) // 2]

    samples = []
    for _ in range(30):
        t0 = _time.perf_counter()
        check_conflict(db, tt, probe, slot.weekday, slot.period_no, span=1)
        samples.append((_time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    median = samples[len(samples) // 2]
    assert p95 < 100, (
        f"60 班 {placed} 格下 check-conflict p95 {p95:.1f}ms"
        f"(中位數 {median:.1f}ms、最慢 {samples[-1]:.1f}ms),超過 100ms 目標"
    )
