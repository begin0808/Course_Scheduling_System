"""M3-5:無解衝突定位與部分排課。

三種人造無解情境,共同點是**每一項單獨看都很合理**——正是市售系統只會回一句
「排不出來」的那類問題。這裡要求報告精確指出是哪幾件事湊在一起,並附上數字。

部分排課的結果一律再交給 `validator` 檢查:除了被明確放寬的那類約束以外,
其餘硬約束必須一格都沒違反。「少排幾節」不可以偷偷變成「排錯幾節」。
"""

import pytest

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import conflict_explainer, preflight
from app.solver.conflict_explainer import explain
from app.solver.model_builder import (
    Relaxation,
    SolveOptions,
    SolverInputError,
    solve,
)
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from tests.fixtures import Builder

# 部分排課的最佳解很快就找到,但「證明不可能只少排 1 節」很慢;
# 這裡要驗的是解的品質,不是最佳性證明。
FAST = SolveOptions(max_seconds=25.0, workers=4, random_seed=1)
HARD = SolverConfig.hard_only()

WEEK = [1, 2, 3, 4, 5]


def _block_days(b: Builder, teacher: str, weekdays: list[int]) -> None:
    b.unavailable_days(teacher, weekdays)


# ── 情境 A:音樂教室的供給被教師時段吃掉 ──────────────────────
def _music_room_fixture(db, year: int = 140) -> Builder:
    """6 班各 5 節音樂,共用唯一的音樂教室(30 節)。

    音樂教室一週有 35 格,兩位音樂老師各教 15 節、可排時段各有 28 格——
    逐項檢查全數通過。但兩人都不排週五,音樂教室週五就沒人能用,
    實際只有 28 格要塞 30 節課。
    """
    b = Builder(db, year, 1, "junior_high")
    b.subject("音樂", required_room_type=RoomType.special)
    b.room("音樂教室", room_type=RoomType.special, subjects=["音樂"])

    for i in (1, 2):
        b.teacher(f"音樂師{i}", base_periods=20)
        b.teacher(f"國文師{i}", base_periods=20)
        b.teacher(f"數學師{i}", base_periods=20)
    for i in (1, 2):
        _block_days(b, f"音樂師{i}", [5])

    for i in range(1, 7):
        b.klass(f"70{i}", grade=7, track=ClassTrack.junior_high.value)

    for i in range(1, 7):
        cls, half = f"70{i}", 1 if i <= 3 else 2
        b.assign(subject="音樂", teachers=[f"音樂師{half}"], periods=5, classes=[cls],
                 room="音樂教室")
        b.assign(subject="國文", teachers=[f"國文師{half}"], periods=5, classes=[cls])
        b.assign(subject="數學", teachers=[f"數學師{half}"], periods=5, classes=[cls])
    return b


def test_room_supply_eaten_by_teacher_rules_is_located(db):
    """驗收①:報告指出場地與數字(需求 30 節 > 實際可用 28 節)。"""
    fx = _music_room_fixture(db).build()
    problem = load_problem(db, fx.semester_id)

    # 逐項的必要條件檢查全數通過——這正是 unsat core 存在的理由
    assert preflight.run(problem).ok

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis", "必要條件都通過,原因只能來自逐項試解"
    assert report.explained
    assert report.complete

    codes = {c.code for c in report.causes}
    assert codes == {"H3", "H4"}, [c.message for c in report.causes]

    room = next(c for c in report.causes if c.code == "H3")
    assert room.scope_name == "音樂教室"
    assert room.detail == {"demand": 30, "supply": 35, "usable": 28, "rooms": 1}
    assert "音樂教室" in room.message
    assert "30" in room.message and "28" in room.message

    # 兩位音樂老師都是共犯,少了任何一位都排得出來
    blamed = {c.scope_name for c in report.causes if c.code == "H4"}
    assert blamed == {"音樂師1", "音樂師2"}
    assert report.mode == "each"
    assert "任何一項" in report.headline
    assert report.relaxable_codes == ("H4",)  # H3 是物理限制,不可放寬


def test_partial_schedule_places_95_percent_and_lists_the_rest(db):
    """驗收③:同一份 fixture 改用部分排課 → 95%+ 排入 + 未排清單。"""
    fx = _music_room_fixture(db, year=141).build()
    problem = load_problem(db, fx.semester_id)
    total = sum(a.periods_per_week for a in problem.assignments)  # 6 班 × 15 節

    result = solve(problem, FAST, config=HARD, relax=Relaxation())
    assert result.solved

    placed = sum(e.span for e in result.entries)
    assert placed == total - result.unplaced_periods
    assert placed / total >= 0.95, f"只排入 {placed}/{total}"

    # 少排的正好是音樂教室塞不下的 2 節,而且說得出是哪一班
    assert result.unplaced_periods == 2
    assert {u.subject_name for u in result.unscheduled} == {"音樂"}
    assert all(len(u.class_names) == 1 for u in result.unscheduled)

    # 「少排幾節」不可以變成「排錯幾節」:除了 H8(週節數不足)外零違反
    codes = {v.code for v in validate(problem, result.entries)}
    assert codes == {"H8"}, codes


def test_partial_schedule_can_relax_teacher_rules_instead(db):
    """勾選放寬「教師不可排時段」→ 全部排入,代價是有課落在老師的不可排時段。"""
    fx = _music_room_fixture(db, year=142).build()
    problem = load_problem(db, fx.semester_id)
    total = sum(a.periods_per_week for a in problem.assignments)

    result = solve(problem, FAST, config=HARD,
                   relax=Relaxation(soft_codes=frozenset({"H4"})))
    assert result.solved
    assert result.unscheduled == (), "放寬 H4 後應該排得下"
    assert sum(e.span for e in result.entries) == total

    violations = validate(problem, result.entries)
    assert {v.code for v in violations} == {"H4"}
    # 只違反最低限度:30 節課、28 格可用 → 至少 2 節得落在週五
    assert len(violations) == 2, [v.message for v in violations]


# ── 情境 B:協同教學的兩位教師沒有共同可排時段 ────────────────
def _co_teaching_fixture(db, year: int = 143) -> Builder:
    """2 節協同教學。節數刻意不超過每日上限,否則「只放寬李師」會被 H10 擋住,
    李師就不算單獨的瓶頸了——這種交互作用正是逐項試解才看得出來的東西。"""
    b = Builder(db, year, 1, "junior_high")
    b.teacher("王師", base_periods=20)
    b.teacher("李師", base_periods=20)
    _block_days(b, "王師", [1, 2, 3, 4])  # 只有週五能上
    _block_days(b, "李師", [5])           # 唯獨週五不能上
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="自然科學", teachers=["王師", "李師"], periods=2, classes=["301"])
    return b


def test_teacher_time_contradiction_names_both_teachers(db):
    """驗收②:報告指出該教師。兩人各自都有足夠可排格數,交集卻是空的。"""
    fx = _co_teaching_fixture(db).build()
    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok  # 王師 2≤7、李師 2≤28,逐項都過

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis"
    assert {c.code for c in report.causes} == {"H4"}
    assert {c.scope_name for c in report.causes} == {"王師", "李師"}
    assert report.mode == "each"

    wang = next(c for c in report.causes if c.scope_name == "王師")
    assert wang.detail == {"assigned": 2, "available": 7, "unavailable": 28}
    assert wang.relaxable


def test_co_teaching_contradiction_is_explained_not_crashed(db):
    """一般求解會在建模階段就發現此配課無任何候選時段;衝突定位仍須給得出人話。"""
    fx = _co_teaching_fixture(db, year=144).build()
    problem = load_problem(db, fx.semester_id)

    with pytest.raises(SolverInputError, match="找不到任何可排"):
        solve(problem, SolveOptions(max_seconds=10.0), config=HARD)

    assert explain(problem, max_seconds=40.0).explained


# ── 情境 C:同班同科目每日上限 ────────────────────────────────
def _daily_cap_fixture(db, year: int = 145) -> Builder:
    b = Builder(db, year, 1, "junior_high")
    b.teacher("陳師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["陳師"], periods=12, classes=["301"])
    return b


def test_daily_subject_cap_conflict_reports_the_arithmetic(db):
    """12 節單節課,每日上限 2 節 × 5 天 = 10 節。報告要把這個算式講出來。"""
    fx = _daily_cap_fixture(db).build()
    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok  # 12 節 ≤ 35 格,逐項檢查看不出問題

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis"

    cause = next(c for c in report.causes if c.code == "H10")
    assert cause.scope_name == "同班同科目每日節數上限"  # 全校旋鈕,不掛學期名稱
    assert "301" in cause.message
    assert cause.detail["singles"] == 12
    assert cause.detail["cap"] == 2
    assert cause.detail["ceiling"] == 10
    assert "12" in cause.message and "10" in cause.message
    assert "連堂" in cause.suggestion
    assert report.relaxable_codes == ("H10",)


def test_relaxing_daily_cap_places_everything(db):
    fx = _daily_cap_fixture(db, year=146).build()
    problem = load_problem(db, fx.semester_id)

    result = solve(problem, FAST, config=HARD,
                   relax=Relaxation(soft_codes=frozenset({"H10"})))
    assert result.solved
    assert result.unscheduled == ()
    assert sum(e.span for e in result.entries) == 12
    assert {v.code for v in validate(problem, result.entries)} == {"H10"}


def test_daily_cap_respects_config(db):
    """上限提高到 3 → 3×5 = 15 ≥ 12,不再無解。"""
    fx = _daily_cap_fixture(db, year=147).build()
    problem = load_problem(db, fx.semester_id)

    report = explain(problem, config=SolverConfig(daily_subject_cap=3), max_seconds=30.0)
    assert report.status == "feasible"
    assert not report.explained


# ── pre-flight 路徑:必要條件不成立時不必啟動 solver ───────────
def test_preflight_failure_short_circuits_the_solver(db):
    b = Builder(db, 148, 1, "junior_high")
    b.teacher("王師", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=30, classes=["301"])
    wang = b.teachers["王師"]
    for p in b.regular_slots():
        if p.weekday in (4, 5):  # 擋掉 14 格 → 可排 21 格 < 30 節
            db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday,
                                   period_no=p.period_no,
                                   rule_type=TeacherRuleType.unavailable.value))
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    report = explain(problem, max_seconds=60.0)
    assert report.source == "preflight"
    assert report.wall_time == 0.0, "必要條件已是證明,不該啟動 solver"
    assert "必須修正" in report.headline

    cause = next(c for c in report.causes if c.code == "teacher_overload")
    assert "王師" in cause.message
    assert cause.detail == {"assigned": 30, "available": 21, "unavailable": 14}


def test_feasible_problem_reports_no_cause(db):
    b = Builder(db, 149, 1, "junior_high")
    b.teacher("王師", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=4, classes=["301"])
    fx = b.build()

    report = explain(load_problem(db, fx.semester_id), max_seconds=30.0)
    assert report.status == "feasible"
    assert report.causes == ()
    assert report.relaxable_codes == ()
    assert report.headline == ""


# ── 放寬的邊界 ───────────────────────────────────────────────
@pytest.mark.parametrize("code", ["H1", "H2", "H3"])
def test_physical_constraints_cannot_be_relaxed(code):
    """一位教師不能同時出現在兩間教室——那是物理,不是政策。"""
    with pytest.raises(SolverInputError, match="不可放寬"):
        Relaxation(soft_codes=frozenset({code}))


# ── 兩個獨立瓶頸:鬆開任何一個都不夠 ──────────────────────────
def test_two_independent_bottlenecks_must_be_fixed_together(db):
    """音樂教室不夠 + 另一班的國文超過每日上限。兩者互不相干,只解決一個仍然無解。"""
    b = _music_room_fixture(db, year=150)
    b.teacher("陳師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["陳師"], periods=12, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok

    report = explain(problem, max_seconds=90.0)
    assert report.status == "infeasible"
    assert report.mode == "joint", [c.message for c in report.causes]
    assert "必須一起處理" in report.headline

    codes = {c.code for c in report.causes}
    assert len(report.causes) >= 2
    assert "H10" in codes  # 國文那一邊
    assert codes & {"H3", "H4"}  # 音樂教室那一邊


# ── unknown 路徑:沒能判定的試解,不可以被當成「已證明不可行」 ─────
def _fake_probe(monkeypatch, unknown_when):
    """讓指定的試解回 unknown,其餘照常。unknown_when 收 disabled 標籤集合。"""
    real = conflict_explainer.check_feasibility

    def fake(problem, *, config=None, disabled=frozenset(), max_seconds=10.0, workers=8):
        if unknown_when(disabled):
            return "unknown"
        return real(problem, config=config, disabled=disabled,
                    max_seconds=max_seconds, workers=workers)

    monkeypatch.setattr(conflict_explainer, "check_feasibility", fake)


def test_base_probe_unknown_reports_unknown_not_infeasible(db, monkeypatch):
    """連「這份資料到底有沒有解」都沒判定出來時,不可以擺出一份原因報告。"""
    fx = _daily_cap_fixture(db, year=151).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda disabled: not disabled)  # 基準試解逾時

    report = explain(problem, max_seconds=30.0)
    assert report.status == "unknown"
    assert report.causes == ()
    assert report.headline == ""


def test_unknown_step_marks_the_report_incomplete(db, monkeypatch):
    """某個旋鈕的試解逾時 → 它不該被列為原因,但報告必須承認自己不完整。"""
    fx = _music_room_fixture(db, year=152).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda d: any(t.code == "H3" for t in d))

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.mode == "each"
    assert "H3" not in {c.code for c in report.causes}  # 沒證明 → 不敢說
    assert {c.code for c in report.causes} == {"H4"}    # 證明過的照樣列
    assert not report.complete, "有試解沒判定出來,complete 必須是 False"


def test_structural_headline_does_not_overclaim_when_unproven(db, monkeypatch):
    """所有試解都逾時 → 落到 structural,但不可以宣稱「即使放寬所有項目仍然無解」。"""
    fx = _music_room_fixture(db, year=153).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda d: bool(d))  # 除了基準以外全部逾時

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.mode == "structural"
    assert not report.complete
    assert "未能判定" in report.headline
    assert "即使放寬所有可調整的項目仍然無解" not in report.headline
    assert report.causes  # structural 仍要列出最吃緊的班級/教師


def test_structural_headline_is_assertive_when_proven(db):
    """真的證明了「全部放寬仍無解」時,話就該說死。

    一個班配課 40 節 > 可排 35 格:pre-flight 會先攔下,所以這裡直接驗 headline 文案分支。
    """
    report = conflict_explainer.ConflictReport(
        status="infeasible", source="analysis", mode="structural",
        causes=(conflict_explainer.Cause("structural", "class", 1, "301", "x", "y"),),
        complete=True,
    )
    assert report.headline == "即使放寬所有可調整的項目仍然無解,問題出在配課總量"
