"""M3-2:CP-SAT 硬約束建模。

**每個解都用 `app.solver.validator` 逐項驗過**(測試策略總則第 2 點)——
建模寫錯時 solver 會很有信心地交出違反硬約束的「可行解」,不能信它自己說的話。
"""

import time
from dataclasses import replace

import pytest

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import preflight
from app.solver.model_builder import SolveOptions, SolverInputError, solve
from app.solver.problem import FixedEntry
from app.solver.validator import validate
from tests.fixtures import (
    Builder,
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
)

FAST = SolveOptions(max_seconds=120.0, workers=4, random_seed=1)

BUILDERS = {
    "elementary_small": build_elementary_small,
    "junior_high_mid": build_junior_high_mid,
    "vocational_high": build_vocational_high,
}


def _solve_fixture(db, key, **kwargs):
    fx = BUILDERS[key](db)
    problem = load_problem(db, fx.semester_id, **kwargs)
    assert preflight.run(problem).ok
    result = solve(problem, FAST)
    return fx, problem, result


# ── 驗收①:三套 fixtures 各自可解,且零硬約束違反 ──────────────
@pytest.mark.parametrize("key", list(BUILDERS))
def test_fixture_solves_with_zero_violations(key, db):
    _fx, problem, result = _solve_fixture(db, key)
    assert result.solved, f"{key} 應可解,實得 {result.status}"

    violations = validate(problem, result.entries)
    assert not violations, [v.message for v in violations[:5]]

    # 每筆配課都排滿(跑班群組的每門課各自產生格位,故總和 = 各配課週節數之和)
    total = sum(e.span for e in result.entries)
    assert total == sum(a.periods_per_week for a in problem.assignments)


# ── 驗收②:技高的 3 連堂與實習工場 ───────────────────────────
def test_vocational_blocks_are_contiguous_and_workshops_exclusive(db):
    fx, problem, result = _solve_fixture(db, "vocational_high")
    assert result.solved
    assert not validate(problem, result.entries)

    practicum_ids = {
        a.id for a in problem.assignments if a.subject_name == "實習工場"
    }
    blocks = [e for e in result.entries if e.assignment_id in practicum_ids]
    assert len(blocks) == 30  # 15 班 × 2 個 3 連堂
    assert all(e.span == 3 for e in blocks)

    # 連堂涵蓋的三節都是連續的一般課,且不跨午休
    for e in blocks:
        table = problem.table_of(next(a for a in problem.assignments if a.id == e.assignment_id))
        assert table is not None
        covered = [table.slot(e.weekday, e.period_no + k) for k in range(3)]
        assert all(s is not None for s in covered)

    # 實習工場同時段至多一班(D8 互斥)
    occupied: set[tuple[int, int, int]] = set()
    for e in blocks:
        assert e.room_id is not None
        for k in range(3):
            cell = (e.room_id, e.weekday, e.period_no + k)
            assert cell not in occupied, "同一工場同時段排了兩班"
            occupied.add(cell)

    # 業界師資只在週二/週四上課
    external = next(t for t in problem.teachers.values() if t.is_external)
    his = [
        e for e in result.entries
        if external.id in next(
            a for a in problem.assignments if a.id == e.assignment_id
        ).teacher_ids
    ]
    assert his and {e.weekday for e in his} <= {2, 4}


def test_group_courses_share_the_same_slots(db):
    """H7:跑班群組的 5 門選修必須同時段開課。"""
    _fx, problem, result = _solve_fixture(db, "vocational_high")
    group = next(u for u in problem.units.values() if u.is_group)
    members = [a.id for a in problem.assignments if a.unit_id == group.id]

    slots_per_member = {
        aid: sorted((e.weekday, e.period_no) for e in result.entries if e.assignment_id == aid)
        for aid in members
    }
    distinct = {tuple(v) for v in slots_per_member.values()}
    assert len(distinct) == 1, "群組內各門課的時段應完全相同"
    assert len(next(iter(distinct))) == 3  # 每週 3 節


def test_junior_high_assigns_rooms_by_type(db):
    """只指定場地類型的配課,引擎須逐筆挑出合法教室。"""
    _fx, problem, result = _solve_fixture(db, "junior_high_mid")
    art = [a for a in problem.assignments if a.subject_name == "藝術"]
    assert all(a.room_id is None and a.required_room_type == "special" for a in art)

    art_ids = {a.id for a in art}
    art_entries = [e for e in result.entries if e.assignment_id in art_ids]
    assert art_entries and all(e.room_id is not None for e in art_entries)
    chosen = {problem.rooms[e.room_id].name for e in art_entries if e.room_id}
    assert chosen <= {"音樂教室", "美術教室"}, chosen  # room_subjects 限制了候選


# ── 驗收③:鎖定 5 格後重解,位置不變 ─────────────────────────
def test_locked_entries_survive_resolve(db):
    fx = build_elementary_small(db)
    problem = load_problem(db, fx.semester_id)
    first = solve(problem, FAST)
    assert first.solved

    locked = tuple(
        FixedEntry(e.assignment_id, e.weekday, e.period_no, e.span, e.room_id, locked=True)
        for e in first.entries[:5]
    )
    # 換一顆亂數種子重解:若 H9 沒建對,solver 會很樂意把這 5 格搬走
    pinned = replace(problem, fixed_entries=locked)
    second = solve(pinned, SolveOptions(max_seconds=120.0, workers=4, random_seed=99))
    assert second.solved
    assert not validate(pinned, second.entries)

    placed = {(e.assignment_id, e.weekday, e.period_no, e.span) for e in second.entries}
    for f in locked:
        assert (f.assignment_id, f.weekday, f.period_no, f.span) in placed
    assert sum(1 for e in second.entries if e.locked) == 5


# ── 驗收④:12 班國中 fixture 在 60 秒內解出 ──────────────────
def test_junior_high_solves_within_60_seconds(db):
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)
    started = time.perf_counter()
    result = solve(problem, SolveOptions(max_seconds=60.0, workers=4, random_seed=7))
    elapsed = time.perf_counter() - started

    assert result.solved, f"12 班國中應在 60 秒內解出,實得 {result.status}"
    assert elapsed < 60, f"耗時 {elapsed:.1f}s"
    assert not validate(problem, result.entries)


# ── 建模的邊界情形 ───────────────────────────────────────────
def test_infeasible_when_teacher_has_no_free_slot(db):
    """王師兩門課 5+5 節,但只剩 4 格可排 → CP-SAT 證明無解。"""
    b = Builder(db, 130, 1, "junior_high")
    b.teacher("王師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=5, classes=["301"])
    b.assign(subject="數學", teachers=["王師"], periods=5, classes=["301"])
    wang = b.teachers["王師"]
    keep = {(1, 2), (1, 3), (2, 2), (2, 3)}
    for p in b.regular_slots():
        if (p.weekday, p.period_no) not in keep:
            db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday,
                                   period_no=p.period_no,
                                   rule_type=TeacherRuleType.unavailable.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert not preflight.run(problem).ok  # pre-flight 就攔下了(10 節 > 4 格)
    result = solve(problem, SolveOptions(max_seconds=30.0, workers=2))
    assert result.status == "infeasible"


def test_group_with_mismatched_periods_is_rejected(db):
    """跑班群組同時段開課,節數不一致無法建模;pre-flight 也應攔下。"""
    b = Builder(db, 131, 1, "junior_high")
    b.teacher("甲師", base_periods=40)
    b.teacher("乙師", base_periods=40)
    b.klass("201", grade=2, track=ClassTrack.junior_high.value)
    b.klass("202", grade=2, track=ClassTrack.junior_high.value)
    b.group("多元選修", ["201", "202"])
    b.subject("選修甲")
    b.subject("選修乙")
    b.assign(subject="選修甲", teachers=["甲師"], periods=3, group="多元選修")
    b.assign(subject="選修乙", teachers=["乙師"], periods=2, group="多元選修")
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    report = preflight.run(problem)
    issue = next(i for i in report.errors if i.code == "group_shape_mismatch")
    assert "多元選修" in issue.message

    with pytest.raises(SolverInputError, match="無法同時段開課"):
        solve(problem, SolveOptions(max_seconds=5.0))


def test_daily_subject_cap_counts_single_periods_only(db):
    """H10:連堂不計入每日上限,但連堂課剩下的單節仍受限。"""
    b = Builder(db, 132, 1, "junior_high")
    b.teacher("陳師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    # 8 節 = 3 連堂 ×2 + 2 單節
    b.assign(subject="彈性學習", teachers=["陳師"], periods=8, classes=["301"], blocks=(3, 2))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    result = solve(problem, SolveOptions(max_seconds=30.0, workers=2))
    assert result.solved
    assert not validate(problem, result.entries)

    spans = sorted(e.span for e in result.entries)
    assert spans == [1, 1, 3, 3]


def test_room_type_without_any_room_raises(db):
    b = Builder(db, 133, 1, "junior_high")
    b.subject("音樂", required_room_type=RoomType.special)
    b.teacher("音樂師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="音樂", teachers=["音樂師"], periods=2, classes=["301"],
             required_room_type=RoomType.special)
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    with pytest.raises(SolverInputError, match="沒有"):
        solve(problem, SolveOptions(max_seconds=5.0))
