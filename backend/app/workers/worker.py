"""RQ worker 進入點。

兩個 worker 行程,各守一條佇列(M6-2):

    python -m app.workers.worker           # default:自動排課(可佔住數分鐘)
    python -m app.workers.worker ops       # ops:匯出 / 備份 / 還原 / 寄信 + 定時任務

分開的理由是快慢任務不該互相堵住:合在一條佇列時,排課一開跑,組長按匯出就排在後面
等到逾時失敗。**排課永遠只走 default**,ops worker 因此不會載入求解引擎,記憶體預算低得多。

排程器(`with_scheduler=True`)只掛在 ops worker:定時任務(每日備份、心跳)都排進 ops,
由它自己撈回來執行。排課 worker 不跑排程器——它一忙就是好幾分鐘,不該負責準時的事。
"""

import sys

from rq import Worker

from app.workers.queue import QUEUES, ops_queue, redis_conn
from app.workers.scheduler import ensure_scheduled


def main(argv: list[str] | None = None) -> None:
    names = list(argv if argv is not None else sys.argv[1:]) or ["default"]
    unknown = [n for n in names if n not in QUEUES]
    if unknown:
        raise SystemExit(f"未知的佇列名稱:{', '.join(unknown)}(可用:{', '.join(QUEUES)})")

    queues = [QUEUES[n] for n in names]
    runs_scheduler = ops_queue.name in names
    if runs_scheduler:
        ensure_scheduled()
    Worker(queues, connection=redis_conn).work(with_scheduler=runs_scheduler)


if __name__ == "__main__":
    main()
