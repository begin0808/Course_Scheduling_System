"""通知寫入(M4-1)。

只負責「把通知落地」。實際的寄送管道(站內鈴鐺、Email、v2 的 webhook/LINE)
由 M4-3 以 `NotificationChannel` 介面接在這個寫入點之後——寫入永遠成功,
寄送可以失敗、可以重試,兩者不該綁在同一個交易裡。

呼叫端負責 commit。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationType


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
    n = Notification(
        semester_id=semester_id, teacher_id=teacher_id, type=type.value,
        title=title[:120], body=body, link=link[:200],
    )
    db.add(n)
    return n


def for_teacher(db: Session, semester_id: int, teacher_id: int) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.semester_id == semester_id,
                Notification.teacher_id == teacher_id,
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
    )
