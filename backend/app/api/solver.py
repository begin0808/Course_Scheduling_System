"""排課引擎 API。M3-1 僅 pre-flight 檢查報告;自動排課於 M3-4 加入。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role
from app.schemas.solver import PreflightIssue, PreflightOut
from app.services.solver_data import load_problem
from app.solver import preflight

router = APIRouter(tags=["solver"])

viewer = require_roles(Role.scheduler, Role.director)


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
