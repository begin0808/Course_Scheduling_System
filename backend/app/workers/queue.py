"""RQ 佇列與連線設定。排課、寄信、備份等背景任務皆透過此佇列派送。"""

from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.redis_url)

# 預設佇列;後續可依需求分出 solver / email / backup 專用佇列
default_queue = Queue("default", connection=redis_conn)

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

    default_queue.enqueue(send_notification_email, to, subject, body, job_timeout=60)


class RenderError(RuntimeError):
    """PDF/PNG 渲染失敗或逾時(呼叫端轉為 5xx)。"""


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
    job = default_queue.enqueue(func, html, job_timeout=timeout + 30, result_ttl=120)
    result = job.latest_result(timeout=timeout)
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

    單一 worker 序列執行:排課可佔住 10 分鐘,期間丟進去的還原會排在後面。若不擋下,
    api 端會逾時回「失敗」,但 worker 空下來後仍會執行還原——資料庫被無預警覆蓋。
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
    job = default_queue.enqueue(func, *args, job_timeout=timeout + 30, result_ttl=300)
    result = job.latest_result(timeout=timeout)
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
