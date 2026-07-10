"""全域系統設定:SMTP 寄信(M4-3)。管理員專用。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.schemas.notification import SmtpSettingsIn, SmtpSettingsOut
from app.services import email as email_service
from app.services import settings as app_settings

router = APIRouter(tags=["settings"])

admin_only = require_roles(Role.admin)


def _smtp_out(db: Session) -> SmtpSettingsOut:
    cfg = app_settings.smtp_config(db)
    return SmtpSettingsOut(
        host=cfg.host, port=cfg.port, user=cfg.user, sender=cfg.sender,
        use_tls=cfg.use_tls, configured=cfg.configured, has_password=bool(cfg.password),
    )


@router.get("/settings/smtp", response_model=SmtpSettingsOut)
def get_smtp(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """SMTP 設定(不回傳密碼明文)。"""
    return _smtp_out(db)


@router.put("/settings/smtp", response_model=SmtpSettingsOut)
def put_smtp(
    body: SmtpSettingsIn, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_smtp(
        db, host=body.host, port=body.port, user=body.user, password=body.password,
        sender=body.sender, use_tls=body.use_tls,
    )
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_smtp",
        target_type="app_setting", target_id=None,
        detail=f"SMTP 設定更新:{body.host}:{body.port}"[:500],
    ))
    db.commit()
    return _smtp_out(db)


@router.post("/settings/smtp/test", status_code=status.HTTP_200_OK)
def test_smtp(
    to: str, db: Session = Depends(get_db), _: User = Depends(admin_only)
):
    """寄一封測試信,當場回報成功或錯誤(不走 RQ,好讓管理員立刻看到結果)。"""
    cfg = app_settings.smtp_config(db)
    if not cfg.configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "尚未設定 SMTP 主機與寄件人")
    try:
        sent = email_service.send(
            db, to=to, subject="排課系統測試信",
            body="這是一封測試信,收到代表 SMTP 設定正確。",
        )
    except Exception as exc:  # noqa: BLE001 - 把 SMTP 錯誤原文回給管理員
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"寄送失敗:{exc}") from exc
    return {"sent": sent, "to": to}
