"""Email 寄送任務(M4-3,RQ)。

通知的站內部分在請求交易內就已落地;Email 走這裡非同步寄出,失敗不影響課務。
"""

import logging

logger = logging.getLogger(__name__)


def send_notification_email(to: str, subject: str, body: str) -> None:
    """RQ 進入點。SMTP 未設定或寄送失敗都只記 log,不拋出——站內通知已送達。"""
    from app.core.db import SessionLocal
    from app.services import email as email_service

    db = SessionLocal()
    try:
        sent = email_service.send(db, to=to, subject=subject, body=body)
        if not sent:
            logger.info("未寄送通知信(SMTP 未設定或無收件人):%s", subject)
    except Exception as exc:  # noqa: BLE001 - 寄信失敗不該讓 worker 崩潰
        logger.warning("寄送通知信失敗(%s):%s", to, exc)
    finally:
        db.close()
