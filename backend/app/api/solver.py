"""排課引擎 API:pre-flight 檢查、軟約束設定、自動排課任務與進度。"""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.timetable import Timetable, TimetableStatus
from app.models.user import Role, User
from app.schemas.solver import (
    AutoScheduleAccepted,
    AutoScheduleRequest,
    ConstraintConfigIn,
    ConstraintConfigOut,
    PreflightIssue,
    PreflightOut,
    RelaxableOption,
    SolveJobOut,
)
from app.services.solver_data import load_config, load_problem, save_config
from app.solver import preflight
from app.solver.model_builder import RELAXABLE_CODES, RELAXABLE_NAMES
from app.solver.problem import DEFAULT_WEIGHTS, MAX_WEIGHT, SOFT_NAMES, SolverConfig
from app.workers import queue as job_queue
from app.workers.progress import (
    ControlAction,
    JobState,
    JobStatus,
    ProgressStore,
    RedisProgressStore,
    is_stale,
)

router = APIRouter(tags=["solver"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def get_progress_store() -> ProgressStore:
    """自動排課的進度儲存。測試以 dependency_overrides 換成記憶體版。"""
    return RedisProgressStore(job_queue.redis_conn)


@router.get("/solver/preflight", response_model=PreflightOut)
def solver_preflight(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    """排課前置檢查:必要條件不成立時直接指出是誰、差幾節,不必等 solver 跑完才知道無解。"""
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    problem = load_problem(db, semester_id)
    report = preflight.run(problem)
    return PreflightOut(
        semester_id=problem.semester_id,
        semester_label=problem.semester_label,
        ok=report.ok,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        issues=[
            PreflightIssue(
                level=i.level, code=i.code, message=i.message,
                subject_type=i.subject_type, subject_id=i.subject_id, detail=i.detail,
            )
            for i in report.issues
        ],
        class_count=len(problem.classes),
        teacher_count=len(problem.teachers),
        assignment_count=len(problem.assignments),
        total_periods=sum(a.periods_per_week for a in problem.assignments),
    )


def _config_out(semester_id: int, config: SolverConfig) -> ConstraintConfigOut:
    return ConstraintConfigOut(
        semester_id=semester_id,
        daily_subject_cap=config.daily_subject_cap,
        teacher_daily_max=config.teacher_daily_max,
        teacher_consecutive_max=config.teacher_consecutive_max,
        weights={code: config.weight(code) for code in DEFAULT_WEIGHTS},
        weight_names=dict(SOFT_NAMES),
    )


@router.get("/solver/config", response_model=ConstraintConfigOut)
def get_constraint_config(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    """軟約束權重與可調參數;未設定過的學期回傳預設值。"""
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return _config_out(semester_id, load_config(db, semester_id))


@router.put("/solver/config", response_model=ConstraintConfigOut)
def put_constraint_config(
    body: ConstraintConfigIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    unknown = set(body.weights) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"未知的軟約束代碼:{'、'.join(sorted(unknown))}"
        )
    if any(w < 0 for w in body.weights.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "權重不可為負數(0 = 關閉該項)")
    # 上限是部分排課的正確性前提,不是美觀限制(見 solver/problem.py MAX_WEIGHT)
    if any(w > MAX_WEIGHT for w in body.weights.values()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"權重上限為 {MAX_WEIGHT};再高會讓部分排課寧可丟課也要滿足軟約束",
        )

    weights = dict(DEFAULT_WEIGHTS) | body.weights
    config = SolverConfig(
        daily_subject_cap=body.daily_subject_cap,
        teacher_daily_max=body.teacher_daily_max,
        teacher_consecutive_max=body.teacher_consecutive_max,
        weights=weights,
    )
    save_config(db, semester_id, config)
    db.commit()
    return _config_out(semester_id, config)


# ── 自動排課任務(M3-4)────────────────
def _job_out(state: JobState) -> SolveJobOut:
    return SolveJobOut(**{k: v for k, v in state.__dict__.items()})


def _get_job(store: ProgressStore, job_id: str) -> JobState:
    state = store.get(job_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到排課任務(可能已過期)")
    return state


@router.post(
    "/timetables/{timetable_id}/auto-schedule",
    response_model=AutoScheduleAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_auto_schedule(
    timetable_id: int,
    body: AutoScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
    store: ProgressStore = Depends(get_progress_store),
):
    """以來源草稿啟動自動排課;結果寫成新草稿,來源不動。

    pre-flight 有錯誤時直接擋下——沒必要讓教學組長等十分鐘才知道資料有問題。
    部分排課模式只擋結構性錯誤:「總量不足」正是它要處理的事(少排幾節,列成清單)。
    """
    tt = db.get(Timetable, timetable_id)
    if tt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到課表")
    if tt.status != TimetableStatus.draft.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "只能以草稿為來源自動排課;請先複製為新草稿"
        )

    unknown = set(body.relax) - set(RELAXABLE_CODES)
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"這些硬約束不可放寬:{'、'.join(sorted(unknown))}",
        )
    if body.relax and not body.allow_partial:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "放寬硬約束只在部分排課模式下有效"
        )

    problem = load_problem(db, tt.semester_id)
    report = preflight.run(problem)
    blocking = preflight.blocking_errors(report, allow_partial=body.allow_partial)
    if blocking:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "資料未通過排課前置檢查,請先修正",
                "issues": [
                    {"level": i.level, "code": i.code, "message": i.message}
                    for i in blocking
                ],
            },
        )

    job_id = uuid.uuid4().hex
    store.create(JobState(
        job_id=job_id, status=JobStatus.queued.value, semester_id=tt.semester_id,
        source_timetable_id=tt.id, source_name=tt.name,
        max_seconds=float(body.max_seconds), heartbeat=time.time(),
        partial=body.allow_partial,
    ))
    job_queue.enqueue_solve(
        job_id, tt.id, float(body.max_seconds), body.seed, user.id, user.username,
        body.allow_partial, list(body.relax),
    )
    return AutoScheduleAccepted(job_id=job_id)


@router.get("/solver/relaxable", response_model=list[RelaxableOption])
def list_relaxable(_: object = Depends(viewer)):
    """部分排課可勾選放寬的硬約束。H1/H2/H3 不在此列:那是物理,不是政策。"""
    return [RelaxableOption(code=c, name=RELAXABLE_NAMES[c]) for c in RELAXABLE_CODES]


@router.get("/solver/jobs/{job_id}", response_model=SolveJobOut)
def get_solve_job(
    job_id: str,
    _: object = Depends(viewer),
    store: ProgressStore = Depends(get_progress_store),
):
    """輪詢進度。worker 失聯時回報明確錯誤,而不是讓前端永遠轉圈。"""
    state = _get_job(store, job_id)
    if is_stale(state):
        state.status = JobStatus.failed.value
        state.error = "排課工作程序中斷(worker 可能已重啟),請重新啟動排課"
        store.update(job_id, status=state.status, error=state.error)
    return _job_out(state)


@router.post("/solver/jobs/{job_id}/stop", response_model=SolveJobOut)
def stop_solve_job(
    job_id: str,
    _: object = Depends(editor),
    store: ProgressStore = Depends(get_progress_store),
):
    """提前結束:停止搜尋但保留當下最佳解,仍會寫出結果草稿。"""
    state = _get_job(store, job_id)
    if not state.done:
        store.request(job_id, ControlAction.stop)
    return _job_out(_get_job(store, job_id))


@router.post("/solver/jobs/{job_id}/cancel", response_model=SolveJobOut)
def cancel_solve_job(
    job_id: str,
    _: object = Depends(editor),
    store: ProgressStore = Depends(get_progress_store),
):
    """取消:停止搜尋並丟棄結果,不產生新草稿。"""
    state = _get_job(store, job_id)
    if not state.done:
        store.request(job_id, ControlAction.cancel)
    return _job_out(_get_job(store, job_id))
