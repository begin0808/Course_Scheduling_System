"""M5-4 全流程總驗收(後端):三套學制 fixtures 走完整條管線——
配課 → 自動排課 → 驗證零硬違反 → 發布 → 請假展開 → 指派代課 → 月結統計。

M3 的建模測試已各自證明三套 fixture「解得出且零硬約束違反」;本檔的價值在於證明
**下游鏈路能吃真實求解結果並組合成立**:發布快照、依已發布課表展開受影響節次、
指派代課、月結鐘點統計,在國小/國中/技高三種學制上一致成立(驗收①的後端嚴謹形式)。

UI 端的連續旅程另見 frontend/e2e/full-journey.spec.ts。
"""

from datetime import date

import pytest

from app.models.leave import LeaveType
from app.models.substitution import SubstitutionType
from app.models.user import Role
from app.services import leaves as leave_svc
from app.services import substitution_stats as stats_svc
from app.services import substitutions as sub_svc
from app.services import timetable_publish as publish_svc
from app.services.availability import Availability
from app.services.solver_data import load_problem
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from app.workers.solve_job import write_result
from tests.conftest import make_user
from tests.dates import MON, SEM_END, SEM_START, on_or_after
from tests.fixtures import (
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
)

# 求解上限只是天花板(fixture 設計為可行,實際遠低於此)。用 hard-only 求解(與 M3
# 建模測試同法):只要可行即停,不掛軟約束目標函數去逼近最佳解(那會跑到天花板)。
SOLVE = SolveOptions(max_seconds=60.0, workers=4, random_seed=1)
HARD = SolverConfig.hard_only()

CASES = [
    ("elementary_small", build_elementary_small),
    ("junior_high_mid", build_junior_high_mid),
    ("vocational_high", build_vocational_high),
]

# 請假日必須落在「今日之後」:代課處置會拒絕已結束的節次(clock.is_past_slot)。
# 一律由執行當日推算(tests/dates.py),硬編日期會在某天過期並讓整套測試無聲轉紅。
_SEM_START = SEM_START
_SEM_END = SEM_END


def _first_date_with_isoweekday(weekday: int) -> date:
    """基準週(必在未來)中 isoweekday 等於 weekday 的那一天(1=週一)。"""
    day = on_or_after(weekday, MON)
    assert _SEM_START <= day <= _SEM_END
    return day


def _pick_teacher_and_weekday(db, published):
    """從已發布課表取一筆格位,回傳其主教教師與星期(該教師該星期必有課)。"""
    from app.models.assignment import CourseAssignment

    entry = published.entries[0]
    assignment = db.get(CourseAssignment, entry.course_assignment_id)
    lead = next((t for t in assignment.teachers if t.is_lead), assignment.teachers[0])
    return lead.teacher_id, entry.weekday


@pytest.mark.parametrize("name,builder", CASES, ids=[c[0] for c in CASES])
def test_full_pipeline_per_track(name, builder, db):
    fx = builder(db)
    sid = fx.semester_id
    scheduler = make_user(db, f"sched_{name}", roles=[Role.scheduler])

    # 學期起訖(請假登記需要);fixture 範本未設。
    fx.semester.start_date = _SEM_START
    fx.semester.end_date = _SEM_END
    db.flush()

    # ── 1) 自動排課:建來源草稿 → 求解 → 零硬違反 → 寫成結果草稿 ──
    from app.models.timetable import Timetable, TimetableStatus

    source = Timetable(semester_id=sid, name="草稿", status=TimetableStatus.draft.value)
    db.add(source)
    db.flush()

    problem = load_problem(db, sid, source)
    result = solve(problem, SOLVE, config=HARD)
    assert result.solved, f"{name} 應可排出完整解"
    assert not validate(problem, result.entries), f"{name} 解不應有硬約束違反"

    drafted = write_result(db, source, result.entries, scheduler.id, scheduler.username,
                           result.objective)
    db.commit()
    assert len(drafted.entries) == len(result.entries) > 0

    # ── 2) 發布:draft → published(不可變快照)──
    published = publish_svc.publish(db, drafted, scheduler, forced=False)
    db.commit()
    assert published.status == TimetableStatus.published.value

    # ── 3) 請假:挑一位有課的教師請整天假 → 依已發布課表展開受影響節次 ──
    teacher_id, weekday = _pick_teacher_and_weekday(db, published)
    teacher = leave_svc.find_teacher(db, sid, teacher_id)
    assert teacher is not None
    leave_day = _first_date_with_isoweekday(weekday)

    leave = leave_svc.create(
        db, fx.semester, teacher,
        leave_type=LeaveType.personal.value,
        start_date=leave_day, start_time=None, end_date=leave_day, end_time=None,
        reason="全流程測試", created_by_user_id=scheduler.id,
        created_by_name=scheduler.username, notify_teacher=False,
    )
    db.commit()
    affected = list(leave.affected_periods)
    assert affected, f"{name} 請假整天應展開至少一節受影響課"

    # ── 4) 代課:為其中一節找一位當時段有空的教師指派代課 ──
    av = Availability(db, sid)
    assigned = None
    for ap in affected:
        for cand in fx.teachers.values():
            if cand.id in (teacher_id,):
                continue
            try:
                sub = sub_svc.assign(
                    db, ap, sub_type=SubstitutionType.substitute.value,
                    handler_teacher_id=cand.id, counts_toward_hours=None,
                    funding_source="", swap_entry_id=None, swap_date=None,
                    created_by_user_id=scheduler.id, created_by_name=scheduler.username,
                    availability=av,
                )
                assigned = (ap, cand, sub)
                break
            except sub_svc.SubstitutionError:
                continue
        if assigned:
            break
    db.commit()
    assert assigned, f"{name} 應能為受影響節次找到一位可代課教師"
    ap, handler, sub = assigned
    assert sub.handler_teacher_id == handler.id
    assert sub.counts_toward_hours is True  # 代課預設計費

    # ── 5) 月結統計:代課那節所在月份,接手教師應有 1 節代課且計費 ──
    report = stats_svc.monthly_report(db, sid, ap.date.year, ap.date.month)
    summary = next((s for s in report.summaries if s.teacher_id == handler.id), None)
    assert summary is not None, f"{name} 月結應包含接手代課的教師"
    assert summary.handled_count >= 1
    assert summary.billable_count >= 1
    detail = next((d for d in report.details if d.handler_teacher_id == handler.id), None)
    assert detail is not None and detail.sub_type == SubstitutionType.substitute.value
