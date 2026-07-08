"""RQ 佇列與連線設定。排課、寄信、備份等背景任務皆透過此佇列派送。"""

from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.redis_url)

# 預設佇列;後續可依需求分出 solver / email / backup 專用佇列
default_queue = Queue("default", connection=redis_conn)
