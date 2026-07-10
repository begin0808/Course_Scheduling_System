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
