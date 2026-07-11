"""備份/還原背景任務(worker;pg_dump/pg_restore 只在 worker 映像,M5-2)。"""

import logging

from app.services import backup as backup_service

logger = logging.getLogger(__name__)


def _as_dict(info: backup_service.BackupInfo) -> dict:
    return {
        "name": info.name,
        "size_bytes": info.size_bytes,
        "created_at": info.created_at.isoformat(),
        "reason": info.reason,
    }


def create_backup_job(reason: str = "manual") -> dict:
    info = backup_service.create_backup(reason)
    logger.info("已建立備份 %s(%d bytes)", info.name, info.size_bytes)
    return _as_dict(info)


def restore_job(name: str) -> list[str]:
    """還原指定備份;完成後強制全員重新登入。回傳可忽略的警告摘要。"""
    warnings = backup_service.restore_backup(name)
    from app.core.session_epoch import force_logout_all
    force_logout_all()
    logger.info("已從 %s 還原,並要求全員重新登入", name)
    return warnings


def daily_backup_job() -> dict:
    """每日自動備份;執行後把下一次排進去(自我續期,見 scheduler)。

    續期一定要發生,否則一次備份失敗(磁碟滿、DB 暫時不可達)就會讓整條每日備份鏈
    永久靜默斷裂。故先在 finally 把下一次排進去,再讓本次的錯誤照常往上拋(RQ 記失敗)。
    """
    from app.workers.scheduler import schedule_daily_backup
    try:
        info = backup_service.create_backup("auto")
        logger.info("每日自動備份完成 %s", info.name)
        return _as_dict(info)
    finally:
        schedule_daily_backup()
