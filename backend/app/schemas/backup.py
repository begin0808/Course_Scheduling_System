"""備份與還原 schema(M5-2)。"""

from datetime import datetime

from pydantic import BaseModel

_REASON_CN = {
    "manual": "手動",
    "auto": "每日自動",
    "presafe": "還原前保護",
    "upload": "上傳",
}


class BackupOut(BaseModel):
    name: str
    size_bytes: int
    created_at: datetime
    reason: str
    reason_label: str = ""

    @classmethod
    def of(cls, name: str, size_bytes: int, created_at: datetime, reason: str) -> "BackupOut":
        return cls(
            name=name, size_bytes=size_bytes, created_at=created_at,
            reason=reason, reason_label=_REASON_CN.get(reason, reason),
        )


class RestoreResult(BaseModel):
    restored_from: str
    presafe_backup: str  # 還原前自動建立的現狀備份(可反悔)
