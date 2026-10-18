"""api 容器啟動時的資料庫遷移:**要改資料表結構前,先自動備份一次**(v1.3.0)。

起因:v1.3.0 是第一個改動資料表結構的版本。使用 `IMAGE_TAG=latest` 的學校一拉新映像就會
升級,不會先看到「升級前請備份」的說明;結構升級後,舊版程式就認不得新結構。所以由系統自己
在升級前備份,學校什麼都不用做,事後也能在「系統管理 → 資料備份與還原」找到這份備份還原。

規則(使用者定案):
- 只在「資料庫已經有資料、而且結構不是最新」時備份;全新安裝與結構已是最新都不備份。
- 備份失敗**照常升級**,並記下原因讓系統管理員看到。拒絕啟動會讓用 latest 的學校整套
  系統停擺,而結構升級本身不修改既有資料(已在多個舊版的實際資料上驗證)。
- 這份備份不參與每日備份的輪替(見 `services.backup.prune`),由組長自己決定何時刪除。

用法(entrypoint.sh 呼叫):python -m app.scripts.migrate
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("migrate")

PRE_UPGRADE = "preupgrade"  # 備份檔名的 reason:backup_YYYYMMDD_HHMMSS_preupgrade.dump


@dataclass(frozen=True, slots=True)
class Outcome:
    upgraded: bool          # 這次有沒有升級結構
    backup: str = ""        # 升級前備份的檔名
    error: str = ""         # 備份失敗的原因(仍照常升級)


def prepare_and_upgrade(
    current: str | None,
    head: str,
    backup: Callable[[], str],
    upgrade: Callable[[], None],
) -> Outcome:
    """決定要不要先備份,再升級結構。`backup` 回傳備份檔名,失敗時擲例外。

    current 為 None = 資料庫沒有任何遷移紀錄(全新安裝):沒有資料可備份。
    """
    if current is None or current == head:
        upgrade()  # 全新安裝要建表;已是最新則什麼也不做(與先前的 alembic upgrade head 相同)
        return Outcome(upgraded=current is None)
    name, error = "", ""
    try:
        name = backup()
        logger.warning("[migrate] 升級前已自動備份:%s", name)
    except Exception as exc:  # noqa: BLE001 - 備份失敗不阻止升級(使用者定案)
        error = str(exc)[:300] or exc.__class__.__name__
        logger.error("[migrate] 升級前自動備份失敗,仍照常升級:%s", error)
    upgrade()
    return Outcome(upgraded=True, backup=name, error=error)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    from alembic import command
    from app.core.config import settings
    from app.services import backup as backup_service
    from app.services import update_check

    cfg = Config("alembic.ini")
    head = ScriptDirectory.from_config(cfg).get_current_head() or ""
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()

    outcome = prepare_and_upgrade(
        current, head,
        backup=lambda: backup_service.create_backup(PRE_UPGRADE).name,
        upgrade=lambda: command.upgrade(cfg, "head"),
    )
    if not outcome.upgraded or current is None:
        return
    _record(current, head, update_check.current_version(), outcome)


def _record(from_rev: str, to_rev: str, version: str, outcome: Outcome) -> None:
    """記下這次升級,系統管理頁據此提示一次(見 services.upgrade_notice)。"""
    from app.core.db import SessionLocal
    from app.services import upgrade_notice

    db = SessionLocal()
    try:
        upgrade_notice.save(db, {
            "version": version, "from_revision": from_rev, "to_revision": to_rev,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "backup": outcome.backup, "error": outcome.error,
        })
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 提示寫不進去不影響系統運作
        logger.error("[migrate] 無法記錄升級提示:%s", json.dumps(str(exc), ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
