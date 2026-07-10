"""M3-3:軟約束與目標函數(S1–S8)。

比較性測試:斷言**方向性**(開啟後違反數下降),不斷言絕對分數——軟約束是加權
折衷,任何絕對門檻都會在權重微調時變成假警報。

達成度報告與建模一樣不共用程式碼(`report.evaluate` 從課表重新推導),
所以「開啟 S2 後違反數下降」是由獨立的觀測者說的,不是由目標函數自己說的。
"""

import pytest

from app.models.basedata import ClassTrack, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import report
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import DEFAULT_WEIGHTS, SolvedEntry, SolverConfig
from app.solver.validator import validate
from tests.fixtures import Builder, build_junior_high_mid

OPTS = SolveOptions(max_seconds=45.0, workers=4, random_seed=5)


def _only(code: str, **params) -> SolverConfig:
    """只開啟指定的一項軟約束,其餘關閉——比較時才不會被其他項的折衷干擾。"""
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0)
    weights[code] = DEFAULT_WEIGHTS[code]
    return SolverConfig(weights=weights, **params)


def _off() -> SolverConfig:
    return SolverConfig.hard_only()


# ── 驗收①:開/關 S2(同科分散)比較 ─────────────────────────
def test_s2_spread_reduces_same_day_repeats(db):
    """同班同科目同日 ≥2 節的數量,開啟 S2 後應顯著下降。"""
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)

    off = solve(problem, OPTS, config=_off())
    on = solve(problem, OPTS, config=_only("S2"))
    assert off.solved and on.solved
    assert not validate(problem, off.entries)
    assert not validate(problem, on.entries)

    before = report.evaluate(problem, off.entries).get("S2").violations
    after = report.evaluate(problem, on.entries).get("S2").violations
    assert before > 0, "純硬約束的解本來就該出現同日重複,否則這個比較沒有意義"
    assert after < before, f"開啟 S2 後同日重複應下降,實得 {before} → {after}"
    assert after <= before // 2, f"下降幅度應顯著,實得 {before} → {after}"


# ── 驗收②:教師 avoid 時段在有替代方案時被避開 ────────────────
@pytest.fixture
def avoidable(db):
    """王師 4 節課、35 格可排;把週五整天標為 avoid(軟)——有大量替代方案。"""
    b = Builder(db, 150, 1, "junior_high")
    b.teacher("王師", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=4, classes=["301"])
    wang = b.teachers["王師"]
    for p in b.regular_slots():
        if p.weekday == 5:
            db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday,
                                   period_no=p.period_no,
                                   rule_type=TeacherRuleType.avoid.value))
    return b.build()


def test_avoid_slots_are_dodged_when_alternatives_exist(avoidable, db):
    problem = load_problem(db, avoidable.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved
    assert not validate(problem, result.entries)

    assert all(e.weekday != 5 for e in result.entries), "有替代方案時不應排在 avoid 時段"
    assert report.evaluate(problem, result.entries).get("S1").violations == 0


def test_avoid_is_soft_not_hard(db):
    """avoid 只是軟約束:沒有替代方案時仍會排進去,而報告要如實列出。"""
    b = Builder(db, 151, 1, "junior_high")
    b.teacher("王師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=4, classes=["301"])
    wang = b.teachers["王師"]
    for p in b.regular_slots():  # 全部時段都標為盡量避開 → 只能硬排
        db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday, period_no=p.period_no,
                               rule_type=TeacherRuleType.avoid.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved, "avoid 是軟約束,不得讓問題變成無解"

    score = report.evaluate(problem, result.entries).get("S1")
    assert score.violations == 4


def test_prefer_slots_are_favoured(db):
    """prefer 時段在其他條件相同時應被優先選用。"""
    b = Builder(db, 152, 1, "junior_high")
    b.teacher("王師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=2, classes=["301"])
    wang = b.teachers["王師"]
    for weekday in (1, 2):  # 只偏好週一/週二的第一節(period_no 2)
        db.add(TeacherTimeRule(teacher_id=wang.id, weekday=weekday, period_no=2,
                               rule_type=TeacherRuleType.prefer.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved
    assert sorted((e.weekday, e.period_no) for e in result.entries) == [(1, 2), (2, 2)]


# ── 驗收③:報告列出人話明細 ──────────────────────────────────
def test_report_details_are_human_readable(db):
    """「教師王師 週四第七節 被排課(該時段標記為盡量避開)」。"""
    b = Builder(db, 153, 1, "junior_high")
    b.teacher("王師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    a = b.assign(subject="國文", teachers=["王師"], periods=1, classes=["301"])[0]
    db.add(TeacherTimeRule(teacher_id=b.teachers["王師"].id, weekday=4, period_no=9,
                           rule_type=TeacherRuleType.avoid.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    entries = [SolvedEntry(a.id, 4, 9, 1, None)]  # 硬排在 avoid 格

    rep = report.evaluate(problem, entries)
    s1 = rep.get("S1")
    assert s1.violations == 1
    assert s1.details == ("教師王師 週四第七節 被排課(該時段標記為盡量避開)",)
    assert s1.opportunities == 1 and s1.satisfied == 0 and s1.rate == 0.0
    assert s1.penalty == DEFAULT_WEIGHTS["S1"]

    s8 = rep.get("S8")
    assert "偏好未達成最多的是教師王師(1 節)" in s8.details[0]


def test_report_covers_all_eight_soft_constraints(db):
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_off())
    rep = report.evaluate(problem, result.entries)

    assert [i.code for i in rep.items] == [f"S{n}" for n in range(1, 9)]
    assert all(0.0 <= i.rate <= 1.0 for i in rep.items)
    assert rep.total_penalty == sum(i.penalty for i in rep.items)


# ── 其餘軟約束的方向性 ───────────────────────────────────────
def test_s3_daily_load_cap_reduces_heavy_days(db):
    """教師每日授課上限:開啟 S3 後,超過上限的教師×日組合數下降。"""
    b = Builder(db, 154, 1, "junior_high")
    b.teacher("王師", base_periods=40)
    for i in range(1, 5):
        b.klass(f"30{i}", grade=3, track=ClassTrack.junior_high.value)
        b.assign(subject="國文", teachers=["王師"], periods=5, classes=[f"30{i}"])
    fx = b.build()  # 20 節分佈在 5 天 → 若不管,可能某天塞 7 節
    problem = load_problem(db, fx.semester_id)

    cfg_off = _off()
    cfg_on = _only("S3", teacher_daily_max=4)
    off = solve(problem, OPTS, config=cfg_off)
    on = solve(problem, OPTS, config=cfg_on)
    assert off.solved and on.solved

    before = report.evaluate(problem, off.entries, cfg_on).get("S3").violations
    after = report.evaluate(problem, on.entries, cfg_on).get("S3").violations
    assert after <= before
    assert after == 0, "20 節分 5 天,每日 4 節剛好排得下"


def test_s5_major_subjects_move_to_morning(db):
    """主科標記後,開啟 S5 應把主科從下午移到上午。"""
    b = Builder(db, 155, 1, "junior_high")
    b.subject("國文", is_major=True)
    b.teacher("王師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="國文", teachers=["王師"], periods=4, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert all(a.subject_is_major for a in problem.assignments)

    result = solve(problem, OPTS, config=_only("S5"))
    assert result.solved
    score = report.evaluate(problem, result.entries).get("S5")
    assert score.violations == 0, "上午有 4 節一般課/天,主科不必排到下午"
    assert score.opportunities == 4


def test_s7_homeroom_teacher_takes_first_period(db):
    b = Builder(db, 156, 1, "junior_high")
    b.teacher("導師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value, homeroom="導師")
    b.assign(subject="國文", teachers=["導師"], periods=5, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert problem.classes[b.classes["301"].id].homeroom_teacher_id == b.teachers["導師"].id

    result = solve(problem, OPTS, config=_only("S7"))
    assert result.solved
    # 國中範本每日第一節的 period_no 是 2(1 是早自習,非一般課)
    assert all(e.period_no == 2 for e in result.entries)
    assert report.evaluate(problem, result.entries).get("S7").violations == 0


def test_weight_zero_disables_the_constraint(db):
    """權重 0 = 關閉;目標函數不含該項,報告仍照實計算違反數。"""
    problem = load_problem(db, build_junior_high_mid(db).semester_id)
    result = solve(problem, OPTS, config=_off())
    assert result.solved
    assert result.objective == 0.0  # 沒有目標函數 → 純可行性問題

    rep = report.evaluate(problem, result.entries, _off())
    assert all(i.weight == 0 and i.penalty == 0 for i in rep.items)
    assert rep.total_penalty == 0
