"""定時任務排程骨架(M5-0)。

RQ worker 以 `with_scheduler=True` 啟動,內建排程器會在到期時把排定的任務丟回佇列。
週期任務用「執行時把下一次排進去」的自我續期模式表達——不必額外的 rq-scheduler 套件或
獨立容器(單校部署少一個要顧的行程)。M5-2 的每日備份、條件 A 的選配夜間 sweep 都掛這裡。

心跳任務只證明排程器存活(寫一行 log 並排下一次)。以固定 job_id 續期,重啟不會堆疊。
"""

import logging
from datetime import datetime, timedelta

from rq.registry import ScheduledJobRegistry

from app.core import clock
from app.core.config import settings
from app.workers.queue import default_queue

logger = logging.getLogger(__name__)

HEARTBEAT_JOB_ID = "scheduler-heartbeat"
DAILY_BACKUP_JOB_ID = "daily-backup"


def _interval() -> timedelta:
    return timedelta(seconds=settings.scheduler_heartbeat_seconds)


def _schedule_next() -> None:
    # 固定 job_id:同時只會有一筆待執行的心跳,重複排入會覆蓋而非堆疊
    default_queue.enqueue_in(_interval(), heartbeat, job_id=HEARTBEAT_JOB_ID)


def heartbeat() -> None:
    """排程器存活心跳;執行時把下一次排進去(自我續期)。"""
    logger.info("排程器心跳 OK,下次 %s 後", _interval())
    _schedule_next()


def _next_backup_time() -> datetime:
    """學校時區的下一個 backup_hour 時刻(unaware,供 enqueue_at)。"""
    now = clock.school_now().replace(tzinfo=None)
    target = now.replace(hour=settings.backup_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def schedule_daily_backup() -> None:
    from app.workers.backup_job import daily_backup_job
    default_queue.enqueue_at(_next_backup_time(), daily_backup_job, job_id=DAILY_BACKUP_JOB_ID)


def ensure_scheduled() -> None:
    """worker 啟動時呼叫:確保心跳與每日備份已排入(已存在則略過,重啟不重複)。"""
    try:
        registry = ScheduledJobRegistry(queue=default_queue)
        pending = set(registry.get_job_ids())
        if HEARTBEAT_JOB_ID not in pending:
            _schedule_next()
            logger.info("已排入排程器心跳,間隔 %s", _interval())
        if DAILY_BACKUP_JOB_ID not in pending:
            schedule_daily_backup()
            logger.info("已排入每日自動備份,下次 %s", _next_backup_time())
    except Exception:  # noqa: BLE001 - Redis 不可用不該讓 worker 起不來
        logger.warning("排入定時任務失敗(Redis 不可用?);背景任務仍可運作")
