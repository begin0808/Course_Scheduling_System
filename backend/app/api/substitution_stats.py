"""代課鐘點月結統計(M4-5)。

組長/主任看全校並可匯出 Excel;教師只能查自己的明細(`/mine`)。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.substitution_stats import (
    CoverDetailOut,
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
        date_from=report.date_from, date_to=report.date_to,
        year=report.year, month=report.month,
        summaries=[
            TeacherSummaryOut(**{f: getattr(s, f) for f in TeacherSummaryOut.model_fields})
            for s in report.summaries
        ],
        details=[
            StatDetailOut(**{f: getattr(d, f) for f in StatDetailOut.model_fields})
            for d in report.details
        ],
        cover_details=[
            CoverDetailOut(**{f: getattr(d, f) for f in CoverDetailOut.model_fields})
            for d in report.cover_details
        ],
    )


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return sem


# 自訂區間最長一年:結算期間通常是一個月左右,太長多半是選錯了
MAX_RANGE_DAYS = 366


def _check_period(
    year: int | None, month: int | None, date_from: date | None, date_to: date | None,
) -> None:
    """按月(year + month)或自訂區間(date_from + date_to,v1.4.11)擇一。"""
    if date_from is not None or date_to is not None:
        if date_from is None or date_to is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "自訂區間要填起始與結束日期")
        if date_to < date_from:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "結束日期不可早於起始日期")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"統計區間最長 {MAX_RANGE_DAYS} 天")
        return
    if year is None or month is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "請選擇月份或統計區間")
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "月份須為 1~12")


def _report(
    db: Session, semester_id: int, year: int | None, month: int | None,
    date_from: date | None, date_to: date | None, teacher_id: int | None,
) -> stats_service.MonthlyReport:
    _check_period(year, month, date_from, date_to)
    if date_from is not None and date_to is not None:
        return stats_service.range_report(
            db, semester_id, date_from, date_to, teacher_id=teacher_id)
    assert year is not None and month is not None
    return stats_service.monthly_report(db, semester_id, year, month, teacher_id=teacher_id)


@router.get("/substitution-stats", response_model=MonthlyReportOut)
def substitution_stats(
    semester_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """某月(或自訂區間)代課鐘點統計(全校,可篩單一教師)。"""
    _get_semester(db, semester_id)
    return _report_out(_report(db, semester_id, year, month, date_from, date_to, teacher_id))


@router.get("/substitution-stats/mine", response_model=MonthlyReportOut)
def my_substitution_stats(
    semester_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """教師查自己的代課明細。未綁定教師主檔者回空報表。"""
    _get_semester(db, semester_id)
    me = current_teacher(db, user, semester_id)
    if me is None:
        _check_period(year, month, date_from, date_to)
        return MonthlyReportOut(year=year, month=month, date_from=date_from, date_to=date_to)
    return _report_out(_report(db, semester_id, year, month, date_from, date_to, me.id))


@router.get("/substitution-stats/export")
def export_substitution_stats(
    semester_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
) -> Response:
    """匯出某月(或自訂區間)代課鐘點 Excel(彙總 + 明細 + 代導明細三張表)。"""
    _get_semester(db, semester_id)
    report = _report(db, semester_id, year, month, date_from, date_to, teacher_id)
    data = stats_service.build_workbook(report)
    if report.year is not None and report.month is not None:
        filename = f"substitution_hours_{report.year}{report.month:02d}.xlsx"
    else:
        filename = (f"substitution_hours_{report.date_from:%Y%m%d}"
                    f"-{report.date_to:%Y%m%d}.xlsx")
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
