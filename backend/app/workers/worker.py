"""RQ worker 進入點。以 `python -m app.workers.worker` 啟動。

M0-1 階段僅啟動並監聽佇列;實際任務(自動排課、寄信、備份)於 M3–M5 加入。
"""

from rq import Worker

from app.workers.queue import default_queue, redis_conn


def main() -> None:
    worker = Worker([default_queue], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
