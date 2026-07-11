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


def render_export(html: str, fmt: str, *, timeout: int = 90) -> bytes:
    """在 worker 渲染 PDF/PNG,阻塞等待結果並回傳 bytes(api 匯出端點呼叫)。

    api 映像無 WeasyPrint 依賴,故一律派到 worker;結果經 RQ result 取回。
    """
    from app.workers.export_job import render_timetable_pdf, render_timetable_png

    func = render_timetable_pdf if fmt == "pdf" else render_timetable_png
    job = default_queue.enqueue(func, html, job_timeout=timeout + 30, result_ttl=120)
    result = job.latest_result(timeout=timeout)
    if result is None or result.type != result.Type.SUCCESSFUL:
        detail = getattr(result, "exc_string", None) or "未知錯誤"
        raise RenderError(f"課表{fmt.upper()}渲染失敗:{detail}")
    data = result.return_value
    if not isinstance(data, bytes):
        raise RenderError(f"課表{fmt.upper()}渲染回傳非預期型別")
    return data
