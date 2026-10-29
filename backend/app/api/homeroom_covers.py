"""代導(v1.4.0):導師請假當天由誰代他帶班。

和調代課處理相同,限教學組長/教務主任。
"""

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.leaves import cover_out
from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.leave import LEAVE_TYPE_CN, HomeroomCover
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.homeroom_cover import (
    CoverAssignIn,
    CoverAssignOut,
    CoverLogOut,
    CoverOptionOut,
    CoverOptionsOut,
    CoverSkipOut,
    CoverSlipOut,
    CoverSlipRowOut,
    CoverSlipsOut,
)
from app.services import homeroom_covers as cover_service
from app.services import settings as app_settings

router = APIRouter(tags=["homeroom-covers"])

handler_roles = require_roles(Role.scheduler, Role.director)


def _get_cover(db: Session, cover_id: int) -> HomeroomCover:
    cover = db.get(HomeroomCover, cover_id)
    if cover is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這筆代導")
    return cover


def cover_log_out(c: HomeroomCover) -> CoverLogOut:
    leave = c.leave_request
    return CoverLogOut(
        **cover_out(c).model_dump(),
        absent_teacher_name=leave.teacher.name,
        leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
    )


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return sem


@router.get("/homeroom-covers/{cover_id}/options", response_model=CoverOptionsOut)
def cover_options(cover_id: int, db: Session = Depends(get_db), _: User = Depends(handler_roles)):
    """可代導的老師:同年級導師 → 該班任課老師 → 其他老師(有課也可以,整天請假的不列)。"""
    cover = _get_cover(db, cover_id)
    return CoverOptionsOut(options=[
        CoverOptionOut(**asdict(o), group_label=cover_service.GROUP_CN[o.group])
        for o in cover_service.options(db, cover)
    ])


@router.put("/homeroom-covers/{cover_id}", response_model=CoverAssignOut)
def assign_cover(
    cover_id: int,
    body: CoverAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(handler_roles),
):
    """指派代導老師,或標記不需代導;whole_leave 時同一班其他還沒安排的日子一起指派。"""
    cover = _get_cover(db, cover_id)
    try:
        done, skipped = cover_service.assign(
            db, cover, handler_teacher_id=body.handler_teacher_id, no_cover=body.no_cover,
            whole_leave=body.whole_leave, actor_name=user.username,
        )
    except cover_service.CoverError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    who = "不需代導" if body.no_cover else f"由 {cover.handler.name if cover.handler else ''} 代導"
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="assign_homeroom_cover",
        target_type="homeroom_cover", target_id=cover.id,
        detail=(f"{cover.leave_request.teacher.name} 請假,{cover.class_name} "
                f"{', '.join(str(c.date) for c in done)} {who}")[:500],
    ))
    db.commit()
    return CoverAssignOut(
        assigned=len(done),
        skipped=[CoverSkipOut(**asdict(s)) for s in skipped],
    )


@router.delete("/homeroom-covers/{cover_id}", status_code=status.HTTP_200_OK)
def clear_cover(cover_id: int, db: Session = Depends(get_db), user: User = Depends(handler_roles)):
    """撤回:退回待代導,原代導老師收到取消通知。"""
    cover = _get_cover(db, cover_id)
    try:
        cover_service.clear(db, cover, actor_name=user.username)
    except cover_service.CoverError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="clear_homeroom_cover",
        target_type="homeroom_cover", target_id=cover.id,
        detail=f"{cover.class_name} {cover.date} 代導退回待安排"[:500],
    ))
    db.commit()
    return {"ok": True}


@router.get("/homeroom-covers", response_model=list[CoverLogOut])
def list_covers(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(handler_roles),
):
    """代導紀錄:依教師(請假的導師或代導老師)、日期區間篩選。"""
    _get_semester(db, semester_id)
    rows = cover_service.query(
        db, semester_id, date_from=date_from, date_to=date_to, teacher_id=teacher_id)
    return [cover_log_out(c) for c in rows]


@router.get("/homeroom-cover-slips", response_model=CoverSlipsOut)
def cover_slips(
    semester_id: int = Query(...),
    cover_ids: list[int] = Query(..., min_length=1, max_length=500),
    db: Session = Depends(get_db),
    _: User = Depends(handler_roles),
):
    """代導通知單:一位代導老師一張。"""
    sem = _get_semester(db, semester_id)
    return CoverSlipsOut(
        school_name=app_settings.school_name(db),
        semester_label=sem.label,
        slips=[
            CoverSlipOut(teacher_name=s.teacher_name,
                         rows=[CoverSlipRowOut(**asdict(r)) for r in s.rows])
            for s in cover_service.slips(db, semester_id, cover_ids)
        ],
    )
