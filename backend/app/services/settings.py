"""全域系統設定的讀寫(M4-3)。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

# 校名。顯示於介面、匯出的課表(Excel/PDF/PNG)、代課通知信與 A4 公告單。
#
# 先前只能在安裝時以 .env 的 SCHOOL_NAME 指定,要改就得編輯檔案並重啟容器——
# 對只會用網頁的教學組長來說形同改不了。現在存在資料庫,可隨時於系統管理修改;
# 未設定時沿用 .env 的值,既有部署升級後行為不變。
SCHOOL_NAME = "school_name"

# 超鐘點上限:一位教師每週配課節數,最多可超出其「應授節數」幾節。
# 依各縣市/各校規定自訂(臺南市實務約 8 節)。0 = 不限制。
#
# 為什麼是「應授 + N」而不是固定值:應授本身就因身分而異——以臺南市為例,
# 國文科專任 16 節、兼任導師 11 節、兼任主任 6 節,固定上限對誰都不合適。
MAX_OVERTIME = "max_overtime_periods"
DEFAULT_MAX_OVERTIME = 8

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


def school_name(db: Session) -> str:
    """校名。系統設定優先,未設定時沿用安裝時 .env 的 SCHOOL_NAME。"""
    from app.core.config import settings as env_settings

    return get(db, SCHOOL_NAME).strip() or env_settings.school_name


def save_school_name(db: Session, value: str) -> None:
    set_value(db, SCHOOL_NAME, value.strip())


def max_overtime(db: Session) -> int:
    """超鐘點上限(節)。未設定或值毀損時回預設值,不讓設定問題擋住配課作業。"""
    raw = get(db, MAX_OVERTIME)
    if not raw:
        return DEFAULT_MAX_OVERTIME
    try:
        return max(int(raw), 0)
    except ValueError:
        return DEFAULT_MAX_OVERTIME


def save_max_overtime(db: Session, value: int) -> None:
    set_value(db, MAX_OVERTIME, str(max(value, 0)))


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
