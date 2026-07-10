"""M3-1:問題描述轉換與 pre-flight 檢查。

驗收①:三套 fixtures 皆可轉出問題描述且 pre-flight 通過
驗收②:人為製造「王師 22 節但可排 20 格」→ 報告明確指出教師與數字
"""

import pytest

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import preflight
from app.solver.problem import BlockSpec, Slot, max_non_overlapping, slots_overlap
from tests.fixtures import (
    Builder,
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
)

BUILDERS = {
    "elementary_small": (build_elementary_small, 6, 31),
    "junior_high_mid": (build_junior_high_mid, 12, 35),
    "vocational_high": (build_vocational_high, 15, 40),
}


def _codes(report) -> set[str]:
    return {i.code for i in report.issues}


# ── 驗收①:三套 fixtures 轉得出問題描述,pre-flight 全過 ──────────
@pytest.mark.parametrize("key", list(BUILDERS))
def test_fixtures_convert_and_pass_preflight(key, db):
    build, num_classes, slot_count = BUILDERS[key]
    fx = build(db)

    problem = load_problem(db, fx.semester_id)
    assert len(problem.classes) == num_classes
    assert len(problem.assignments) == len(fx.assignments)
    assert all(len(t.slots) == slot_count for t in problem.tables.values())
    # 節次表已解析到班級上,solver 不需再回退
    assert all(c.period_table_id in problem.tables for c in problem.classes.values())

    report = preflight.run(problem)
    assert report.ok, f"{key} pre-flight 應通過,卻回報:{[i.message for i in report.errors]}"
    assert not report.warnings, [i.message for i in report.warnings]


def test_vocational_problem_keeps_group_and_blocks(db):
    fx = build_vocational_high(db)
    problem = load_problem(db, fx.semester_id)

    group = next(u for u in problem.units.values() if u.is_group)
    assert len(group.class_ids) == 6
    # 跑班群組同時段開課:班級只被佔掉 3 節,而非 5 門 × 3 節
    assert problem.unit_slot_consumption(group.id) == 3

    practicum = [a for a in problem.assignments if a.subject_name == "實習工場"]
    assert len(practicum) == 15
    assert all(a.blocks == (BlockSpec(size=3, count=2),) for a in practicum)

    external = next(t for t in problem.teachers.values() if t.is_external)
    # 週一/三/五 各 8 節一般課不可排
    assert len(external.unavailable) == 24
    assert preflight.teacher_available_slots(problem, external) == 16


# ── 驗收②:王師 22 節但可排 20 格 ──────────────────────────────
@pytest.fixture
def overloaded(db):
    """國中範本 35 格一般課;把王師 15 格標為不可排 → 可排 20 格,卻配了 22 節。"""
    b = Builder(db, 120, 1, "junior_high")
    b.teacher("王師", base_periods=22)  # 應授 22 節,故不會另外觸發超鐘點警告
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.klass("302", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=11, classes=["301"])
    b.assign(subject="數學", teachers=["王師"], periods=11, classes=["302"])

    wang = b.teachers["王師"]
    blocked = [p for p in b.regular_slots() if p.weekday in (3, 4, 5)][:15]
    for p in blocked:
        db.add(TeacherTimeRule(
            teacher_id=wang.id, weekday=p.weekday, period_no=p.period_no,
            rule_type=TeacherRuleType.unavailable.value,
        ))
    return b.build()


def test_teacher_overload_names_teacher_and_numbers(overloaded, db):
    problem = load_problem(db, overloaded.semester_id)
    report = preflight.run(problem)

    assert not report.ok
    issue = next(i for i in report.errors if i.code == "teacher_overload")
    assert "王師" in issue.message
    assert "22 節" in issue.message
    assert "20 格" in issue.message
    assert issue.detail == {"assigned": 22, "available": 20, "unavailable": 15}
    assert issue.subject_type == "teacher"
    assert issue.subject_id == overloaded.teachers["王師"].id


def test_teacher_over_hours_is_warning_not_error(db):
    """配課超出應授鐘點只是提醒(超鐘點費),不影響能否排出課表。"""
    b = Builder(db, 121, 1, "junior_high")
    b.teacher("李師", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["李師"], periods=24, classes=["301"])
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok  # 24 ≤ 35 可排格數
    warning = next(i for i in report.warnings if i.code == "teacher_over_hours")
    assert "李師" in warning.message and "24 節" in warning.message


# ── 其他必要條件 ──────────────────────────────────────────────
def test_class_overload(db):
    b = Builder(db, 122, 1, "junior_high")
    b.teacher("甲師", base_periods=40)
    b.teacher("乙師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["甲師"], periods=20, classes=["301"])
    b.assign(subject="數學", teachers=["乙師"], periods=20, classes=["301"])
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "class_overload")
    assert "301" in issue.message and "40 節" in issue.message and "35 節" in issue.message


def test_room_supply_shortage(db):
    """§3.4 的範例:音樂教室需求 > 供給。"""
    b = Builder(db, 123, 1, "junior_high")
    b.subject("音樂")
    b.room("音樂教室", room_type=RoomType.special, capacity=35)
    for i in range(1, 13):
        b.teacher(f"音樂師{i}", base_periods=40)
        b.klass(f"90{i}", grade=9, track=ClassTrack.junior_high.value)
        b.assign(subject="音樂", teachers=[f"音樂師{i}"], periods=3,
                 classes=[f"90{i}"], room="音樂教室")
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "room_supply")
    assert "音樂教室" in issue.message
    assert issue.detail == {"demand": 36, "supply": 35}


def test_room_type_supply_shortage(db):
    """只指定場地類型時,以該類型的場地總數估供給。"""
    b = Builder(db, 124, 1, "junior_high")
    b.subject("音樂", required_room_type=RoomType.special)
    b.room("音樂教室", room_type=RoomType.special, capacity=35)
    for i in range(1, 13):
        b.teacher(f"音樂師{i}", base_periods=40)
        b.klass(f"90{i}", grade=9, track=ClassTrack.junior_high.value)
        b.assign(subject="音樂", teachers=[f"音樂師{i}"], periods=3,
                 classes=[f"90{i}"], required_room_type=RoomType.special)
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "room_type_supply")
    assert "專科教室" in issue.message and "36 節" in issue.message


def test_room_capacity_is_warning_only(db):
    """D8:容量不參與求解,只在 pre-flight 提醒人數超過。"""
    b = Builder(db, 125, 1, "junior_high")
    b.teacher("師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value, student_count=40)
    b.room("小教室", room_type=RoomType.special, capacity=25)
    b.assign(subject="國文", teachers=["師"], periods=3, classes=["301"], room="小教室")
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok
    warning = next(i for i in report.warnings if i.code == "room_capacity")
    assert "小教室" in warning.message and "40 人" in warning.message


def test_block_longer_than_contiguous_run(db):
    """國中範本上午 4 節、下午 3 節連續;5 連堂放不進去。"""
    b = Builder(db, 126, 1, "junior_high")
    b.teacher("師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="彈性學習", teachers=["師"], periods=5, classes=["301"], blocks=(5, 1))
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "block_infeasible")
    assert "5 連堂" in issue.message and "4 節" in issue.message


# ── D7 牆鐘重疊(純函式)────────────────────────────────────
def _slot(weekday, pno, start, end):
    return Slot(weekday=weekday, period_no=pno, name=f"第{pno}節",
                start_min=start, end_min=end)


def test_slots_overlap_same_table_uses_period_no():
    a = _slot(1, 3, 10 * 60 + 10, 11 * 60)
    b = _slot(1, 3, 9 * 60, 10 * 60)  # 時間不重疊,但同表同節次
    assert slots_overlap(a, b, same_table=True)
    assert not slots_overlap(a, _slot(1, 4, 10 * 60 + 10, 11 * 60), same_table=True)


def test_slots_overlap_cross_table_uses_wall_clock():
    # 國小 40 分/節第 4 節 10:30–11:10 vs 高中 50 分/節第 3 節 10:10–11:00
    elem = _slot(1, 4, 10 * 60 + 30, 11 * 60 + 10)
    high = _slot(1, 3, 10 * 60 + 10, 11 * 60)
    assert slots_overlap(elem, high, same_table=False)
    assert not slots_overlap(elem, _slot(1, 3, 9 * 60, 10 * 60), same_table=False)
    assert not slots_overlap(elem, _slot(2, 3, 10 * 60 + 10, 11 * 60), same_table=False)


def test_max_non_overlapping_dedups_cross_table_slots():
    same_day = [
        _slot(1, 1, 480, 530),   # 08:00–08:50
        _slot(1, 2, 540, 590),   # 09:00–09:50
        _slot(1, 1, 490, 520),   # 另一套表,與第一節重疊
    ]
    assert max_non_overlapping(same_day) == 2
    # 不同星期各自計算
    assert max_non_overlapping(same_day + [_slot(2, 1, 480, 530)]) == 3


def test_cross_table_teacher_has_fewer_available_slots(db):
    """完全中學:同一位教師任教國中部(45分)與高中部(50分),可排格數少於兩表之和。"""
    from app.services.templates import build_period_table_from_template, get_template

    b = Builder(db, 127, 1, "junior_high")
    template = get_template("senior_high")
    assert template is not None
    senior = build_period_table_from_template(template, name="高中部節次表")
    b.semester.period_tables.append(senior)
    db.flush()

    b.teacher("跨部師", base_periods=80)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    jh_class = b.classes["301"]
    b.klass("101", grade=1, track=ClassTrack.senior_high.value)
    b.classes["101"].period_table_id = senior.id
    db.flush()

    b.assign(subject="國文", teachers=["跨部師"], periods=3, classes=["301"])
    b.assign(subject="數學", teachers=["跨部師"], periods=3, classes=["101"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert problem.classes[jh_class.id].period_table_id != problem.classes[
        b.classes["101"].id
    ].period_table_id

    teacher = problem.teachers[b.teachers["跨部師"].id]
    tables = problem.tables_of_teacher(teacher.id)
    assert len(tables) == 2
    naive_sum = sum(len(t.slots) for t in tables)  # 35 + 40 = 75
    available = preflight.teacher_available_slots(problem, teacher)
    assert available < naive_sum, "跨節次表的節次在牆鐘上重疊,不可直接相加"
    assert available >= max(len(t.slots) for t in tables)


# ── M3-5:哪些錯誤擋得住「部分排課」 ─────────────────────────
def _issue(code: str, detail: dict | None = None) -> preflight.Issue:
    return preflight.Issue("error", code, "x", "semester", 1, detail or {})


def test_partial_mode_only_blocks_on_structural_errors():
    """總量不足正是部分排課要處理的事;結構性錯誤則連模型都建不起來。"""
    report = preflight.PreflightReport((
        _issue("class_overload"), _issue("teacher_overload"), _issue("room_supply"),
        _issue("block_infeasible"), _issue("group_shape_mismatch"),
    ))
    assert len(preflight.blocking_errors(report, allow_partial=False)) == 5
    codes = {i.code for i in preflight.blocking_errors(report, allow_partial=True)}
    assert codes == {"block_infeasible", "group_shape_mismatch"}


def test_partial_mode_blocks_when_a_room_type_has_no_room_at_all():
    """供給 0 = 一間都沒有 → 建模就會失敗;供給不足則可以少排幾節。"""
    none_at_all = preflight.PreflightReport((_issue("room_type_supply", {"supply": 0}),))
    not_enough = preflight.PreflightReport((_issue("room_type_supply", {"supply": 30}),))
    assert preflight.blocking_errors(none_at_all, allow_partial=True)
    assert not preflight.blocking_errors(not_enough, allow_partial=True)


# ── 場地供給必須與建模端的候選集合同義(不只看類型,也看適用科目)──
def _room_type_fixture(db, year: int, *, bind_subject: str | None):
    b = Builder(db, year, 1, "junior_high")
    b.subject("音樂", required_room_type=RoomType.special)
    b.subject("美術", required_room_type=RoomType.special)
    # 全校唯一一間專科教室;bind_subject 決定它適用哪一科(空=不限)
    b.room("美術教室", room_type=RoomType.special,
           subjects=[bind_subject] if bind_subject else None)
    b.teacher("音樂師", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="音樂", teachers=["音樂師"], periods=2, classes=["301"],
             required_room_type=RoomType.special)
    return b.build()


def test_room_supply_respects_subject_applicability(db):
    """唯一的專科教室只適用美術,音樂課卻要求專科教室 → 建模必然失敗,pre-flight 要先攔下。"""
    fx = _room_type_fixture(db, 170, bind_subject="美術")
    report = preflight.run(load_problem(db, fx.semester_id))

    issue = next(i for i in report.errors if i.code == "room_no_candidate")
    assert "音樂" in issue.message
    # 這是結構性錯誤:少排幾節課也救不了,部分排課同樣要擋
    assert preflight.blocking_errors(report, allow_partial=True)


def test_room_supply_passes_when_the_room_applies_to_the_subject(db):
    fx = _room_type_fixture(db, 171, bind_subject=None)
    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok, [i.message for i in report.errors]


def test_room_type_demand_is_grouped_by_candidate_pool(db):
    """兩門課同樣要專科教室,但可用的教室集合不同 → 需求不可相加。"""
    b = Builder(db, 172, 1, "junior_high")
    b.subject("音樂", required_room_type=RoomType.special)
    b.subject("美術", required_room_type=RoomType.special)
    b.room("音樂教室", room_type=RoomType.special, subjects=["音樂"])
    b.room("美術教室", room_type=RoomType.special, subjects=["美術"])
    b.teacher("音樂師", base_periods=40)
    b.teacher("美術師", base_periods=40)
    for i in range(1, 6):
        b.klass(f"30{i}", grade=3, track=ClassTrack.junior_high.value)
        b.assign(subject="音樂", teachers=["音樂師"], periods=4, classes=[f"30{i}"],
                 required_room_type=RoomType.special)
        b.assign(subject="美術", teachers=["美術師"], periods=4, classes=[f"30{i}"],
                 required_room_type=RoomType.special)
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    report = preflight.run(problem)
    # 各池需求 20 節 ≤ 單間供給 35 節;若把兩池相加(40)再比對「2 間 × 35」仍會過,
    # 但把 40 節硬塞進「音樂教室」就會誤報。這裡確認沒有誤報。
    assert not [i for i in report.errors if i.code == "room_type_supply"]
