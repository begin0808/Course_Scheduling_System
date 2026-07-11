"""代課鐘點月結統計(M4-5)。

組長/主任看全校並可匯出 Excel;教師只能查自己的明細(`/mine`)。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.substitution_stats import (
    MonthlyReportOut,
    StatDetailOut,
    TeacherSummaryOut,
)
from app.services import substitution_stats as stats_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["substitution-stats"])

viewer = require_roles(Role.scheduler, Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _report_out(report: stats_service.MonthlyReport) -> MonthlyReportOut:
    return MonthlyReportOut(
        year=report.year, month=report.month,
        summaries=[
            TeacherSummaryOut(**{f: getattr(s, f) for f in TeacherSummaryOut.model_fields})
            for s in report.summaries
        ],
        details=[
            StatDetailOut(**{f: getattr(d, f) for f in StatDetailOut.model_fields})
            for d in report.details
        ],
    )


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return sem


def _check_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "月份須為 1~12")


@router.get("/substitution-stats", response_model=MonthlyReportOut)
def substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """某月代課鐘點統計(全校,可篩單一教師)。"""
    _get_semester(db, semester_id)
    _check_month(month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=teacher_id)
    return _report_out(report)


@router.get("/substitution-stats/mine", response_model=MonthlyReportOut)
def my_substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """教師查自己的代課明細。未綁定教師主檔者回空報表。"""
    _get_semester(db, semester_id)
    _check_month(month)
    me = current_teacher(db, user, semester_id)
    if me is None:
        return MonthlyReportOut(year=year, month=month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=me.id)
    return _report_out(report)


@router.get("/substitution-stats/export")
def export_substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
) -> Response:
    """匯出某月代課鐘點 Excel(彙總 + 明細兩張表)。"""
    _get_semester(db, semester_id)
    _check_month(month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=teacher_id)
    data = stats_service.build_workbook(report)
    filename = f"substitution_hours_{year}{month:02d}.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
