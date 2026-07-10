"""全域系統設定的讀寫(M4-3)。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

# SMTP 設定的 key
SMTP_HOST = "smtp_host"
SMTP_PORT = "smtp_port"
SMTP_USER = "smtp_user"
SMTP_PASSWORD = "smtp_password"
SMTP_FROM = "smtp_from"
SMTP_TLS = "smtp_tls"


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    use_tls: bool

    @property
    def configured(self) -> bool:
        """只要有主機與寄件人即視為已設定;帳密可空(內網轉發常見)。"""
        return bool(self.host and self.sender)


def get(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def all_settings(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.scalars(select(AppSetting))}


def smtp_config(db: Session) -> SmtpConfig:
    values = all_settings(db)
    return SmtpConfig(
        host=values.get(SMTP_HOST, ""),
        port=int(values.get(SMTP_PORT) or 25),
        user=values.get(SMTP_USER, ""),
        password=values.get(SMTP_PASSWORD, ""),
        sender=values.get(SMTP_FROM, ""),
        use_tls=values.get(SMTP_TLS, "") == "1",
    )


def save_smtp(
    db: Session, *, host: str, port: int, user: str, password: str, sender: str, use_tls: bool
) -> None:
    set_value(db, SMTP_HOST, host.strip())
    set_value(db, SMTP_PORT, str(port))
    set_value(db, SMTP_USER, user.strip())
    # 空密碼視為「不變更」,避免每次存設定都要重打密碼
    if password:
        set_value(db, SMTP_PASSWORD, password)
    set_value(db, SMTP_FROM, sender.strip())
    set_value(db, SMTP_TLS, "1" if use_tls else "0")
