"""升級提示(v1.3.0):資料表結構升級後,提醒系統管理員一次。

`app.scripts.migrate` 在升級結構後寫入;系統管理頁的「系統版本」卡片讀取並顯示,
按「知道了」後清除。內容是升級前自動備份的檔名(或備份失敗的原因),
讓沒看過升級說明的學校(例如使用 latest 映像)也知道有這份備份、要退回時怎麼做。
"""

import json

from sqlalchemy.orm import Session

from app.services import settings as settings_service

KEY = "upgrade_notice"


def get(db: Session) -> dict | None:
    raw = settings_service.get(db, KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def save(db: Session, notice: dict) -> None:
    settings_service.set_value(db, KEY, json.dumps(notice, ensure_ascii=False))


def dismiss(db: Session) -> None:
    settings_service.set_value(db, KEY, "")
