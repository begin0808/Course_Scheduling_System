"""通知:教師端(鈴鐺、確認收到)與組長看板(確認狀態、再次提醒)(M4-3)。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.notification import Notification
from app.models.user import Role, User
from app.schemas.notification import (
    NotificationListOut,
    NotificationOut,
    TeacherNotificationStatus,
    UnreadCountOut,
)
from app.services import notifications as notif_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["notifications"])

registrar = require_roles(Role.scheduler, Role.director)


# ── 教師端 ────────────────────────────────
@router.get("/notifications/mine", response_model=NotificationListOut)
def my_notifications(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """本人的通知(最新在前)與未讀數。未綁定教師主檔者回空清單。"""
    me = current_teacher(db, user, semester_id)
    if me is None:
        return NotificationListOut(items=[], unread=0)
    items = notif_service.for_teacher(db, semester_id, me.id)
    return NotificationListOut(
        items=[NotificationOut.model_validate(n) for n in items],
        unread=sum(1 for n in items if n.read_at is None),
    )


@router.get("/notifications/mine/unread-count", response_model=UnreadCountOut)
def my_unread_count(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """鈴鐺的未讀數(輪詢用,刻意輕量)。"""
    me = current_teacher(db, user, semester_id)
    if me is None:
        return UnreadCountOut(unread=0)
    return UnreadCountOut(unread=notif_service.unread_count(db, semester_id, me.id))


def _get_own_notification(db: Session, notification_id: int, user: User) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到通知")
    me = current_teacher(db, user, n.semester_id)
    if me is None or n.teacher_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能存取自己的通知")
    return n


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    n = _get_own_notification(db, notification_id, user)
    notif_service.mark_read(n)
    db.commit()
    return NotificationOut.model_validate(n)


@router.post("/notifications/{notification_id}/acknowledge", response_model=NotificationOut)
def acknowledge(
    notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    """「確認收到」——通知層的已讀確認,不影響課務狀態(指派即生效)。"""
    n = _get_own_notification(db, notification_id, user)
    notif_service.acknowledge(n)
    db.commit()
    return NotificationOut.model_validate(n)


# ── 組長看板 ──────────────────────────────
@router.get("/notifications", response_model=list[TeacherNotificationStatus])
def board(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    unacknowledged_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(registrar),
):
    """全校通知的確認狀態;可篩教師、可只看未確認者。"""
    stmt = select(Notification).where(Notification.semester_id == semester_id)
    if teacher_id is not None:
        stmt = stmt.where(Notification.teacher_id == teacher_id)
    if unacknowledged_only:
        stmt = stmt.where(Notification.acknowledged_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.id.desc())).all()
    return [
        TeacherNotificationStatus(
            id=n.id, type=n.type, title=n.title,
            teacher_id=n.teacher_id, teacher_name=n.teacher.name if n.teacher else "(已移除)",
            created_at=n.created_at, read_at=n.read_at, acknowledged_at=n.acknowledged_at,
        )
        for n in rows
    ]


@router.post("/notifications/{notification_id}/remind", response_model=NotificationOut)
def remind(
    notification_id: int, db: Session = Depends(get_db), _: User = Depends(registrar)
):
    """再次提醒:對未確認的通知重發一則(站內 + Email 依設定)。"""
    original = db.get(Notification, notification_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到通知")
    if original.acknowledged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "此通知已被確認,無需再提醒")

    from app.models.notification import NotificationType

    resent = notif_service.notify(
        db, semester_id=original.semester_id, teacher_id=original.teacher_id,
        type=NotificationType(original.type),
        title=f"【再次提醒】{original.title}", body=original.body, link=original.link,
    )
    db.commit()
    return NotificationOut.model_validate(resent)
