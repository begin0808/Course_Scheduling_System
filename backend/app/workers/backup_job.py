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


def restore_job(name: str) -> bool:
    """還原指定備份;完成後強制全員重新登入。"""
    backup_service.restore_backup(name)
    from app.core.session_epoch import force_logout_all
    force_logout_all()
    logger.info("已從 %s 還原,並要求全員重新登入", name)
    return True


def daily_backup_job() -> dict:
    """每日自動備份;執行後把下一次排進去(自我續期,見 scheduler)。"""
    info = backup_service.create_backup("auto")
    logger.info("每日自動備份完成 %s", info.name)
    from app.workers.scheduler import schedule_daily_backup
    schedule_daily_backup()
    return _as_dict(info)
