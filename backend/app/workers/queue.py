"""RQ 佇列與連線設定。排課、寄信、備份等背景任務皆透過此佇列派送。"""

import time

from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.redis_url)

# 兩條佇列,兩個 worker 行程(M6-2)。分開的理由是「快慢任務不該互相堵住」:
#   default → 自動排課。60 班可跑數分鐘,期間這個 worker 完全佔住。
#   ops     → 匯出 / 備份 / 還原 / 寄信。都是秒級,但正是排課那幾分鐘裡組長最常按的。
# 合在一條佇列時,排課一開跑,匯出就排在後面等到逾時失敗(M5 複審 A)。
default_queue = Queue("default", connection=redis_conn)
ops_queue = Queue("ops", connection=redis_conn)

QUEUES = {q.name: q for q in (default_queue, ops_queue)}

# 求解逾時後仍需時間寫回結果,無解時還要跑衝突定位;RQ 的看門狗要比 solver 的 timeout 寬鬆。
# 被 RQ 砍掉的話,使用者等了十分鐘卻連「為什麼排不出來」都拿不到。
JOB_TIMEOUT_MARGIN = 240


def enqueue_solve(
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None,
    username: str,
    allow_partial: bool = False,
    relax: list[str] | None = None,
) -> None:
    """把自動排課任務丟進佇列(API 層呼叫;測試以假佇列取代)。"""
    from app.workers.solve_job import run_auto_schedule

    default_queue.enqueue(
        run_auto_schedule,
        job_id, timetable_id, max_seconds, seed, user_id, username,
        allow_partial, relax or [],
        job_id=job_id,
        job_timeout=int(max_seconds) + JOB_TIMEOUT_MARGIN,
    )


def enqueue_email(to: str, subject: str, body: str) -> None:
    """把一封通知信丟進佇列(通知服務於交易 commit 後呼叫)。"""
    from app.workers.email_job import send_notification_email

    ops_queue.enqueue(send_notification_email, to, subject, body, job_timeout=60)


class RenderError(RuntimeError):
    """PDF/PNG 渲染失敗或逾時(呼叫端轉為 5xx)。"""


RESULT_POLL_INTERVAL = 0.5


def _wait_result(job, timeout: int):
    """輪詢等待 job 的最新結果;逾時回 None。

    不用 RQ 的 `latest_result(timeout=...)`:它以 XREAD 阻塞讀等結果,redis-py 8
    (RESP3 成為預設)之後結果寫入不會喚醒阻塞中的讀端,最後以 socket 逾時收場
    (2026-07-13 CI 首跑抓到:worker 6 秒完成 PNG 渲染,api 卻等到逾時回 500;
    本機映像因 pip layer 快取仍是舊版 redis-py 而測不到)。改為每 0.5s 以
    XREVRANGE 輪詢,對任何 client 版本/協定都成立,延遲對匯出/備份無感。
    """
    deadline = time.monotonic() + timeout
    while True:
        result = job.latest_result()  # 非阻塞:XREVRANGE count=1
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            return None
        time.sleep(RESULT_POLL_INTERVAL)


def _cancel_quietly(job) -> None:
    """逾時後把仍在佇列中的 job 取消,避免 worker 空下來後才「補跑」一個沒人等的任務
    (對還原尤其危險:api 已回失敗,幾分鐘後資料庫卻被無預警覆蓋)。"""
    try:
        job.cancel()
    except Exception:  # noqa: BLE001 - 取消失敗不影響對呼叫端的錯誤回報
        pass


def render_export(html: str, fmt: str, *, timeout: int = 90) -> bytes:
    """在 worker 渲染 PDF/PNG,阻塞等待結果並回傳 bytes(api 匯出端點呼叫)。

    api 映像無 WeasyPrint 依賴,故一律派到 worker;結果經 RQ result 取回。
    """
    from app.workers.export_job import render_timetable_pdf, render_timetable_png

    func = render_timetable_pdf if fmt == "pdf" else render_timetable_png
    job = ops_queue.enqueue(func, html, job_timeout=timeout + 30, result_ttl=120)
    result = _wait_result(job, timeout)
    if result is None or result.type != result.Type.SUCCESSFUL:
        if result is None:
            _cancel_quietly(job)
        detail = getattr(result, "exc_string", None) or "背景忙碌或逾時,請稍後再試"
        raise RenderError(f"課表{fmt.upper()}渲染失敗:{detail}")
    data = result.return_value
    if not isinstance(data, bytes):
        raise RenderError(f"課表{fmt.upper()}渲染回傳非預期型別")
    return data


def solver_busy() -> bool:
    """是否有自動排課任務正在執行或排隊中(供還原前置檢查)。

    分佇列後(M6-2)還原不再排在排課後面等,但這道關口仍然必要——**這是資料安全,不是排隊**:
    還原會 pg_restore --clean 覆蓋整個資料庫,而排課中的 worker 正要把結果寫回同一個庫。
    兩者同時進行,寫回的草稿會落進一個剛被抹掉的世界。故排課進行中一律拒絕還原(409)。
    只看 default 佇列即可:排課永遠只走這條。
    """
    from rq.registry import StartedJobRegistry

    def _is_solve(job) -> bool:
        return bool(job and job.func_name and "run_auto_schedule" in job.func_name)

    try:
        started = StartedJobRegistry(queue=default_queue)
        for jid in started.get_job_ids():
            if _is_solve(default_queue.fetch_job(jid)):
                return True
        return any(_is_solve(job) for job in default_queue.jobs)
    except Exception:  # noqa: BLE001 - 無法判斷時保守放行(不因 Redis 抖動擋住還原)
        return False


class BackupJobError(RuntimeError):
    """備份/還原任務失敗或逾時(呼叫端轉為 5xx)。"""


def _run_blocking(func, *args, timeout: int):
    job = ops_queue.enqueue(func, *args, job_timeout=timeout + 30, result_ttl=300)
    result = _wait_result(job, timeout)
    if result is None or result.type != result.Type.SUCCESSFUL:
        if result is None:
            _cancel_quietly(job)  # 逾時的任務不留在佇列裡等著晚點才跑
        detail = getattr(result, "exc_string", None) or "背景忙碌或逾時"
        raise BackupJobError(detail)
    return result.return_value


def run_backup(reason: str = "manual", *, timeout: int = 120) -> dict:
    """在 worker 跑 pg_dump,阻塞等待並回傳備份資訊(api 呼叫)。"""
    from app.workers.backup_job import create_backup_job
    return _run_blocking(create_backup_job, reason, timeout=timeout)


def run_restore(name: str, *, timeout: int = 180) -> list[str]:
    """在 worker 跑 pg_restore,阻塞等待完成(api 呼叫)。回傳可忽略的警告摘要。"""
    from app.workers.backup_job import restore_job
    return _run_blocking(restore_job, name, timeout=timeout)
