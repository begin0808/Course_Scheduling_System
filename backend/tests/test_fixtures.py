"""M3-0:三套學制驗證資料集的煙霧測試。

驗證兩件事:
1. **結構**:三套 builder 在乾淨資料庫建出完整學期,且各自具備卡片要求的特徵。
2. **自洽**:資料滿足排課的必要條件——無超鐘點、教師配課 ≤ 可排格數、
   班級節數 ≤ 可排格數、場地需求 ≤ 供給、連堂放得進連續的一般課區段、
   跑班群組成員同節次表。

必要條件不等於充分條件:「CP-SAT 可排出全解」須待 M3-2 以獨立 validator 驗證。
這裡攔的是資料本身的錯誤(pre-flight 會在 M3-1 對真實資料做同樣的檢查)。
"""

import pytest
from sqlalchemy import select

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassTrack, RoomType
from app.models.period import Period, PeriodType
from app.services import period_tables as pt_service
from app.services.assignments import class_loads, teacher_loads
from tests.fixtures import (
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
    room_demand,
    teacher_available_slots,
)

BUILDERS = {
    "elementary_small": (build_elementary_small, 6, 31),
    "junior_high_mid": (build_junior_high_mid, 12, 35),
    "vocational_high": (build_vocational_high, 15, 40),
}


@pytest.fixture(params=list(BUILDERS))
def fixture_case(request, db):
    build, num_classes, regular_slots = BUILDERS[request.param]
    return build(db), num_classes, regular_slots


# ── 驗收 1:三套 builder 皆建出完整學期 ────────────────────────
def test_builds_complete_semester(fixture_case, db):
    fx, num_classes, regular_slots = fixture_case

    assert fx.semester.id is not None
    assert len(fx.classes) == num_classes
    assert fx.assignments

    regular = db.scalars(
        select(Period).where(
            Period.period_table_id == fx.table.id,
            Period.type == PeriodType.regular.value,
        )
    ).all()
    assert len(regular) == regular_slots

    for c in fx.classes.values():
        assert pt_service.resolve_period_table(db, c) is not None
    for a in fx.assignments:
        assert a.teachers, "每筆配課至少一位教師"
        assert sum(1 for t in a.teachers if t.is_lead) == 1, "恰一位主教"


# ── 驗收 2:資料自洽 ──────────────────────────────────────────
def test_no_teacher_over_hours(fixture_case, db):
    """無教師超鐘點(已配節數 ≤ 基本鐘點 − 行政減課)。"""
    fx, _, _ = fixture_case
    over = [row for row in teacher_loads(db, fx.semester_id) if row["delta"] > 0]
    assert not over, f"超鐘點教師:{[(r['name'], r['assigned'], r['target']) for r in over]}"


def test_teacher_load_within_available_slots(fixture_case, db):
    """教師配課數 ≤ 可排格數(扣除 unavailable 硬約束後)。M3-1 pre-flight 的核心檢查。"""
    fx, _, _ = fixture_case
    loads = {row["teacher_id"]: row for row in teacher_loads(db, fx.semester_id)}
    for t in fx.teachers.values():
        assigned = loads[t.id]["assigned"]
        available = teacher_available_slots(db, fx, t)
        assert assigned <= available, f"{t.name} 配課 {assigned} 節 > 可排 {available} 格"


def test_no_class_over_capacity(fixture_case, db):
    """班級週節數 ≤ 該班節次表的一般課格數。"""
    fx, _, _ = fixture_case
    over = [row for row in class_loads(db, fx.semester_id) if row["over_capacity"]]
    detail = [(r["name"], r["assigned"], r["capacity"]) for r in over]
    assert not over, f"超出可排節數的班級:{detail}"


def test_room_demand_within_supply(fixture_case, db):
    """已綁定場地的配課需求 ≤ 該場地可用格數。"""
    fx, _, regular_slots = fixture_case
    by_id = {r.id: r for r in fx.rooms.values()}
    for room_id, demand in room_demand(fx).items():
        name = by_id[room_id].name
        assert demand <= regular_slots, f"{name} 需求 {demand} 節 > 供給 {regular_slots}"


def test_block_rules_fit_contiguous_regular_run(fixture_case, db):
    """連堂長度放得進某段連續的一般課節次(H6:連續且不跨午休)。"""
    fx, _, _ = fixture_case
    runs = _contiguous_regular_runs(db, fx.table.id)
    longest = max(runs.values(), default=0)
    for a in fx.assignments:
        for rule in a.block_rules:
            assert rule.block_size <= longest, (
                f"配課 {a.id} 連堂 {rule.block_size} 節 > 最長連續一般課區段 {longest} 節"
            )
            assert rule.block_size * rule.count_per_week <= a.periods_per_week


def test_group_members_share_period_table(fixture_case, db):
    """跑班群組成員班級須同節次表(architecture.md D7#4)。"""
    fx, _, _ = fixture_case
    for group in fx.groups.values():
        tables = set()
        for m in group.members:
            table = pt_service.resolve_period_table(db, m.class_unit)
            assert table is not None
            tables.add(table.id)
        assert len(tables) == 1, f"跑班群組「{group.name}」成員節次表不一致"


# ── 各套資料集的特徵(卡片描述逐項對照)────────────────────────
def test_elementary_features(db):
    fx = build_elementary_small(db)

    # 包班:導師教自己班多科
    homeroom = fx.teachers["王雅婷"]  # 三年甲班導師
    taught = [
        a for a in fx.assignments if any(t.teacher_id == homeroom.id for t in a.teachers)
    ]
    assert len(taught) >= 4
    assert {a.subject_id for a in taught} == {
        fx.subjects[n].id for n in ("國語", "數學", "自然", "社會", "綜合活動")
    }

    # 科任:一位教師跨全部 6 班
    pe = fx.teachers["鄭建宏"]
    pe_classes = {
        m.class_unit_id
        for a in fx.assignments
        if any(t.teacher_id == pe.id for t in a.teachers)
        for m in a.scheduling_unit.members
    }
    assert len(pe_classes) == 6

    # 週三下午不排課
    wed_pm = db.scalars(
        select(Period).where(
            Period.period_table_id == fx.table.id,
            Period.weekday == 3,
            Period.period_no.in_([7, 8, 9]),
        )
    ).all()
    assert {p.type for p in wed_pm} == {PeriodType.reserved.value}

    # 導師時間
    homeroom_slot = db.scalar(
        select(Period).where(
            Period.period_table_id == fx.table.id, Period.type == PeriodType.homeroom.value
        )
    )
    assert homeroom_slot is not None and homeroom_slot.name == "導師時間"


def test_junior_high_features(db):
    fx = build_junior_high_mid(db)

    # 兼行政減課教師
    admins = [t for t in fx.teachers.values() if t.admin_reduction > 0]
    assert {t.admin_title for t in admins} == {"教學組長", "訓育組長"}
    loads = {r["teacher_id"]: r for r in teacher_loads(db, fx.semester_id)}
    for t in admins:
        assert loads[t.id]["target"] == t.base_periods - t.admin_reduction
        assert loads[t.id]["assigned"] <= loads[t.id]["target"]

    # 彈性課程
    flexible = [a for a in fx.assignments if a.subject_id == fx.subjects["彈性學習"].id]
    assert len(flexible) == 12 and all(a.periods_per_week == 3 for a in flexible)

    # 每班 33 節
    for row in class_loads(db, fx.semester_id):
        assert row["assigned"] == 33

    # 導師 12 位各帶一班
    homerooms = [c.homeroom_teacher_id for c in fx.classes.values()]
    assert len(set(homerooms)) == 12


def test_vocational_features(db):
    fx = build_vocational_high(db)

    assert {c.department for c in fx.classes.values()} == {"機械科", "電機科", "資訊科"}
    assert all(c.track == ClassTrack.vocational.value for c in fx.classes.values())

    # 3 連堂實習 ×2,綁定實習工場
    practicum = [a for a in fx.assignments if a.subject_id == fx.subjects["實習工場"].id]
    assert len(practicum) == 15
    for a in practicum:
        assert [(r.block_size, r.count_per_week) for r in a.block_rules] == [(3, 2)]
        assert a.required_room_type == RoomType.workshop.value
        assert a.room_id is not None and a.lock_room

    # 業界師資:外聘、僅週二/週四可排
    externals = [t for t in fx.teachers.values() if t.is_external]
    assert len(externals) == 3
    for t in externals:
        blocked = {r.weekday for r in t.time_rules}
        assert blocked == {1, 3, 5}
        assert teacher_available_slots(db, fx, t) == 16  # 2 天 × 8 節

    # 協同教學:三年級實習兩位教師
    co_taught = [a for a in practicum if len(a.teachers) == 2]
    assert len(co_taught) == 3
    for a in co_taught:
        lead = next(t for t in a.teachers if t.is_lead)
        assert lead.teacher.is_external

    # 跑班群組:6 班、5 門選修同時段
    group = fx.groups["二年級多元選修"]
    assert len(group.members) == 6
    electives = db.scalars(
        select(CourseAssignment).where(CourseAssignment.scheduling_unit_id == group.id)
    ).all()
    assert len(electives) == 5
    assert {a.periods_per_week for a in electives} == {3}
    assert len({a.subject_id for a in electives}) == 5, "5 門不同選修(同科目會撞 H10 每日上限)"

    # 跑班群組只佔班級 3 節(而非 5×3=15 節)
    g2 = {row["name"]: row for row in class_loads(db, fx.semester_id)}
    assert g2["機械二甲"]["assigned"] == 35
    assert g2["機械一甲"]["assigned"] == 35


# ── helper ──────────────────────────────────────────────────
def _contiguous_regular_runs(db, table_id: int) -> dict[int, int]:
    """每個星期最長的連續一般課節次段長度(不跨午休/早自習/導師時間)。"""
    periods = db.scalars(
        select(Period)
        .where(Period.period_table_id == table_id)
        .order_by(Period.weekday, Period.period_no)
    ).all()
    longest: dict[int, int] = {}
    run = 0
    prev_key: tuple[int, int] | None = None
    for p in periods:
        contiguous = prev_key is not None and prev_key == (p.weekday, p.period_no - 1)
        if p.type == PeriodType.regular.value:
            run = run + 1 if contiguous else 1
            longest[p.weekday] = max(longest.get(p.weekday, 0), run)
        else:
            run = 0
        prev_key = (p.weekday, p.period_no)
    return longest
