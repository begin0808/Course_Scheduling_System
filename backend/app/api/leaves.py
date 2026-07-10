"""請假登記與受影響節次(M4-1)。

RBAC:教師只能登記/銷自己的假、只看得到自己的假單;
教學組長與教務主任可代登、可看全校、可代銷。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.leave import LEAVE_TYPE_CN, AffectedStatus, LeaveRequest, LeaveType
from app.models.notification import Notification
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.leave import (
    AffectedPeriodOut,
    LeaveCancelled,
    LeaveRequestIn,
    LeaveRequestOut,
    NotificationOut,
)
from app.services import leaves as leave_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["leaves"])

registrar = require_roles(Role.scheduler, Role.director)  # 可代登/代銷


def _is_registrar(user: User) -> bool:
    """可代登/代銷/看全校。admin 一律通過(與 require_roles 一致)。"""
    return bool(user.role_names & {Role.scheduler.value, Role.director.value, Role.admin.value})


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return sem


def _serialize(leave: LeaveRequest) -> LeaveRequestOut:
    periods = sorted(leave.affected_periods, key=lambda p: (p.date, p.period_no))
    return LeaveRequestOut(
        id=leave.id, semester_id=leave.semester_id,
        teacher_id=leave.teacher_id, teacher_name=leave.teacher.name,
        leave_type=leave.leave_type,
        leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
        start_date=leave.start_date, start_time=leave.start_time,
        end_date=leave.end_date, end_time=leave.end_time,
        reason=leave.reason, status=leave.status,
        created_by_name=leave.created_by_name, created_at=leave.created_at,
        affected_count=len(periods),
        pending_count=sum(1 for p in periods if p.status == AffectedStatus.pending.value),
        affected_periods=[
            AffectedPeriodOut(
                **{k: getattr(p, k) for k in (
                    "id", "date", "weekday", "period_no", "period_name", "start_time",
                    "end_time", "subject_name", "class_names", "room_name", "status",
                    "handler_teacher_id",
                )},
                handler_name=p.handler.name if p.handler else None,
            )
            for p in periods
        ],
    )


def _resolve_target_teacher(db: Session, semester_id: int, body_teacher_id: int | None, user: User):
    """代登指定教師;自登則解析登入者綁定的教師主檔。"""
    if body_teacher_id is not None:
        if not _is_registrar(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只有教學組長或教務主任可代為登記")
        teacher = leave_service.find_teacher(db, semester_id, body_teacher_id)
        if teacher is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
        return teacher

    teacher = current_teacher(db, user, semester_id)
    if teacher is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "您的帳號尚未綁定本學期的教師主檔,無法登記請假;請洽教學組長",
        )
    return teacher


@router.post("/leaves", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
def create_leave(
    body: LeaveRequestIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """登記請假,並依已發布課表展開受影響節次。"""
    sem = _get_semester(db, semester_id)
    if body.leave_type not in set(LeaveType):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知的假別:{body.leave_type}")

    teacher = _resolve_target_teacher(db, semester_id, body.teacher_id, user)
    on_behalf = teacher.user_id != user.id

    try:
        leave = leave_service.create(
            db, sem, teacher,
            leave_type=body.leave_type,
            start_date=body.start_date, start_time=body.start_time,
            end_date=body.end_date, end_time=body.end_time,
            reason=body.reason,
            created_by_user_id=user.id, created_by_name=user.username,
            notify_teacher=on_behalf,
        )
    except leave_service.LeaveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_leave",
        target_type="leave_request", target_id=leave.id,
        detail=(
            f"{teacher.name} {leave_service.range_text(leave)}"
            f" {LEAVE_TYPE_CN.get(leave.leave_type, '')},"
            f"受影響 {len(leave.affected_periods)} 節"
        )[:500],
    ))
    db.commit()
    db.refresh(leave)
    return _serialize(leave)


@router.get("/leaves", response_model=list[LeaveRequestOut])
def list_leaves(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """組長看全校;教師只看得到自己的假單(即使指定了別人的 teacher_id)。"""
    _get_semester(db, semester_id)
    stmt = select(LeaveRequest).where(LeaveRequest.semester_id == semester_id)

    if not _is_registrar(user):
        me = current_teacher(db, user, semester_id)
        if me is None:
            return []
        stmt = stmt.where(LeaveRequest.teacher_id == me.id)
    elif teacher_id is not None:
        stmt = stmt.where(LeaveRequest.teacher_id == teacher_id)

    rows = db.scalars(
        stmt.order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc())
    ).unique()
    return [_serialize(leave) for leave in rows]


def _get_leave(db: Session, leave_id: int, user: User) -> LeaveRequest:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到假單")
    if not _is_registrar(user):
        me = current_teacher(db, user, leave.semester_id)
        if me is None or me.id != leave.teacher_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只能存取自己的假單")
    return leave


@router.get("/leaves/{leave_id}", response_model=LeaveRequestOut)
def get_leave(leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    return _serialize(_get_leave(db, leave_id, user))


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveCancelled)
def cancel_leave(
    leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    """銷假:級聯取消所有受影響節次,已被指派的代課教師會收到取消通知。

    已完成的節次不動——那堂課已經上過了,事後銷假不能把歷史抹掉。
    """
    leave = _get_leave(db, leave_id, user)
    try:
        revoked = leave_service.cancel(db, leave, actor_name=user.username)
    except leave_service.LeaveError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    notified = sorted({p.handler.name for p in revoked if p.handler})
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="cancel_leave",
        target_type="leave_request", target_id=leave.id,
        detail=f"{leave.teacher.name} 銷假,取消 {len(revoked)} 節已指派代課"[:500],
    ))
    db.commit()
    return LeaveCancelled(
        id=leave.id, status=leave.status, revoked_count=len(revoked), notified_teachers=notified
    )


@router.get("/leaves/{leave_id}/affected", response_model=list[AffectedPeriodOut])
def list_affected(
    leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    return _serialize(_get_leave(db, leave_id, user)).affected_periods


@router.get("/leave-types", response_model=dict[str, str])
def leave_types(_: object = Depends(get_active_user)):
    return {t.value: LEAVE_TYPE_CN[t] for t in LeaveType}


# ── 通知(M4-1 只做讀取;鈴鐺、未讀數、Email 於 M4-3)────
@router.get("/notifications/mine", response_model=list[NotificationOut])
def my_notifications(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    me = current_teacher(db, user, semester_id)
    if me is None:
        return []
    rows = db.scalars(
        select(Notification)
        .where(Notification.semester_id == semester_id, Notification.teacher_id == me.id)
        .order_by(Notification.id.desc())
    ).all()
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/notifications", response_model=list[NotificationOut])
def all_notifications(
    semester_id: int = Query(...),
    teacher_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(registrar),
):
    """組長檢視某位教師收到的通知(M4-3 的看板會用到)。"""
    rows = db.scalars(
        select(Notification)
        .where(Notification.semester_id == semester_id, Notification.teacher_id == teacher_id)
        .order_by(Notification.id.desc())
    ).all()
    return [NotificationOut.model_validate(n) for n in rows]
