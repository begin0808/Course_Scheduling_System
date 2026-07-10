"""SMTP 寄信(M4-3)。

實際寄送走 RQ(見 workers/email_job.py),不在請求執行緒裡卡住。
SMTP 未設定時 `send` 直接回 False——站內通知已經送達,Email 只是加分,不該讓整個
調代課流程因為沒設信箱而失敗。
"""

import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.services import settings as app_settings


def send(db: Session, *, to: str, subject: str, body: str) -> bool:
    """寄一封信。回傳是否真的送出(未設定 SMTP、或無收件人時回 False)。"""
    if not to:
        return False
    cfg = app_settings.smtp_config(db)
    if not cfg.configured:
        return False

    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or subject)

    with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as server:
        if cfg.use_tls:
            server.starttls()
        if cfg.user:
            server.login(cfg.user, cfg.password)
        server.send_message(msg)
    return True
