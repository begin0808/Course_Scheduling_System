"""通知服務(M4-1 起,M4-3 補齊寄送管道)。

**站內通知永遠送達**:寫入 `notifications` 一列即完成——鈴鐺輪詢讀這張表。
**Email 是加分**:資料 commit 後才排入寄送佇列,寄失敗不影響課務。

寄送以 `NotificationChannel` 分層(architecture.md §5.3):MVP 兩個管道,站內與 Email;
v2 加 webhook / LINE 只需再實作一個 channel、append 進 `CHANNELS`。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.notification import Notification, NotificationType

logger = logging.getLogger(__name__)

_OUTBOX_KEY = "notification_email_outbox"


@dataclass(frozen=True, slots=True)
class _Email:
    to: str
    subject: str
    body: str


# ── 寄送管道 ────────────────────────────────────────────────
class NotificationChannel(Protocol):
    key: str

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        ...


class InAppChannel:
    """站內通知:`notifications` 那一列本身即送達,無額外動作。"""

    key = "in_app"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        return


class EmailChannel:
    """Email:把信放進交易的寄件匣;commit 後由 after_commit 事件排入 RQ。

    這裡不直接 enqueue——交易若回滾,就不該寄出一封對應到不存在通知的信。
    """

    key = "email"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        if teacher is None or not teacher.email:
            return
        outbox = db.info.setdefault(_OUTBOX_KEY, [])
        outbox.append(_Email(
            to=teacher.email,
            subject=f"[{notification_subject_prefix()}] {notification.title}",
            body=notification.body or notification.title,
        ))


CHANNELS: list[NotificationChannel] = [InAppChannel(), EmailChannel()]


def notification_subject_prefix() -> str:
    from app.core.config import settings

    return settings.school_name


# ── 寫入 ────────────────────────────────────────────────────
def notify(
    db: Session,
    *,
    semester_id: int,
    teacher_id: int | None,
    type: NotificationType,
    title: str,
    body: str = "",
    link: str = "",
) -> Notification:
    """建立通知並經各管道送達。呼叫端負責 commit;Email 於 commit 後自動寄出。"""
    n = Notification(
        semester_id=semester_id, teacher_id=teacher_id, type=type.value,
        title=title[:120], body=body, link=link[:200],
    )
    db.add(n)
    teacher = db.get(Teacher, teacher_id) if teacher_id is not None else None
    for channel in CHANNELS:
        channel.deliver(db, n, teacher)
    return n


# ── commit 後把寄件匣排入 RQ ─────────────────────────────────
@event.listens_for(Session, "after_commit")
def _flush_email_outbox(session: Session) -> None:
    outbox: list[_Email] = session.info.pop(_OUTBOX_KEY, [])
    if not outbox:
        return
    try:
        from app.workers.queue import enqueue_email
    except Exception:  # noqa: BLE001 - 測試或無 Redis 環境:靜默略過 Email
        return
    for msg in outbox:
        try:
            enqueue_email(msg.to, msg.subject, msg.body)
        except Exception:  # noqa: BLE001 - 佇列不可用不該讓已成功的交易報錯
            # 站內通知已送達;Email 只是加分。但要留痕,否則 Redis 掛掉時無聲消失無從查起
            logger.warning("代課通知 Email 排入佇列失敗(收件:%s),站內通知不受影響", msg.to)


@event.listens_for(Session, "after_rollback")
def _discard_email_outbox(session: Session) -> None:
    session.info.pop(_OUTBOX_KEY, None)


# ── 讀取與狀態 ──────────────────────────────────────────────
@dataclass
class NotificationView:
    items: list[Notification] = field(default_factory=list)
    unread: int = 0


def for_teacher(db: Session, semester_id: int, teacher_id: int) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.semester_id == semester_id,
                Notification.teacher_id == teacher_id,
            )
            .order_by(Notification.id.desc())
        )
    )


def unread_count(db: Session, semester_id: int, teacher_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.semester_id == semester_id,
            Notification.teacher_id == teacher_id,
            Notification.read_at.is_(None),
        )
    ) or 0


def mark_read(notification: Notification) -> None:
    if notification.read_at is None:
        notification.read_at = datetime.now().astimezone()


def acknowledge(notification: Notification) -> None:
    now = datetime.now().astimezone()
    if notification.read_at is None:
        notification.read_at = now
    notification.acknowledged_at = now
