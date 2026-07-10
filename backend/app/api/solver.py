"""排課引擎 API:pre-flight 檢查報告與軟約束設定。自動排課於 M3-4 加入。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role
from app.schemas.solver import (
    ConstraintConfigIn,
    ConstraintConfigOut,
    PreflightIssue,
    PreflightOut,
)
from app.services.solver_data import load_config, load_problem, save_config
from app.solver import preflight
from app.solver.problem import DEFAULT_WEIGHTS, SOFT_NAMES, SolverConfig

router = APIRouter(tags=["solver"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


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
