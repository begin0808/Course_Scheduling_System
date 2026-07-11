"""今日調代課看板與調代課日誌(M4-4)。

看板/日誌是行政的當日排課與歷史查詢工具,限教學組長/教務主任。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.config import settings
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.substitution_log import DailyBoardOut, LogEntryOut
from app.services import substitution_log as log_service

router = APIRouter(tags=["substitution-log"])

viewer = require_roles(Role.scheduler, Role.director)


def _entry_out(e: log_service.LogEntry) -> LogEntryOut:
    return LogEntryOut(**{f: getattr(e, f) for f in LogEntryOut.model_fields})


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return sem


@router.get("/daily-board", response_model=DailyBoardOut)
def daily_board(
    semester_id: int = Query(...),
    on: date | None = Query(default=None, description="看板日期,預設為學校時區的今天"),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """某一天全校的調代課異動(預設今天);無異動則 entries 為空。"""
    sem = _get_semester(db, semester_id)
    day = on or log_service.school_today()
    entries = log_service.daily_board(db, semester_id, day)
    return DailyBoardOut(
        date=day,
        weekday=day.isoweekday(),
        school_name=settings.school_name,
        semester_label=sem.label,
        entries=[_entry_out(e) for e in entries],
    )


@router.get("/substitution-log", response_model=list[LogEntryOut])
def substitution_log(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    leave_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """調代課歷史查詢:依教師(缺課或代課)、日期區間、假別篩選。"""
    _get_semester(db, semester_id)
    entries = log_service.query(
        db, semester_id,
        date_from=date_from, date_to=date_to,
        teacher_id=teacher_id, leave_type=leave_type,
    )
    return [_entry_out(e) for e in entries]
