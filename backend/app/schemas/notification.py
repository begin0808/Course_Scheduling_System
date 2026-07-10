"""通知與 SMTP 設定 schema(M4-3)。"""

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    link: str
    created_at: datetime
    read_at: datetime | None = None
    acknowledged_at: datetime | None = None

    model_config = {"from_attributes": True}


class NotificationListOut(BaseModel):
    items: list[NotificationOut] = []
    unread: int = 0


class UnreadCountOut(BaseModel):
    unread: int


# 組長看板:某位教師某類通知的確認狀態
class TeacherNotificationStatus(BaseModel):
    id: int
    type: str
    title: str
    teacher_id: int | None = None
    teacher_name: str
    created_at: datetime
    read_at: datetime | None = None
    acknowledged_at: datetime | None = None


# ── SMTP 設定 ────────────────────────────
class SmtpSettingsIn(BaseModel):
    host: str = Field(default="", max_length=200)
    port: int = Field(default=25, ge=1, le=65535)
    user: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=200)  # 空=不變更
    sender: str = Field(default="", max_length=200)
    use_tls: bool = False


class SmtpSettingsOut(BaseModel):
    host: str
    port: int
    user: str
    sender: str
    use_tls: bool
    configured: bool
    has_password: bool  # 是否已存過密碼(不回傳明文)
