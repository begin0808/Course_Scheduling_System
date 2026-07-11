"""RQ worker 進入點。以 `python -m app.workers.worker` 啟動。

背景任務:自動排課(M3)、寄信(M4-3)、PDF 匯出(M5-1)、每日備份(M5-2)。
以 `with_scheduler=True` 啟動內建排程器;啟動時排入週期任務骨架(M5-0)。
"""

from rq import Worker

from app.workers.queue import default_queue, redis_conn
from app.workers.scheduler import ensure_scheduled


def main() -> None:
    ensure_scheduled()
    worker = Worker([default_queue], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
