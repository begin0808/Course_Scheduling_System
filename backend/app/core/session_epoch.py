"""全域「強制重新登入」時點(M5-2)。

session 是無伺服器狀態的簽章 cookie,還原資料庫不會使其失效(除非密碼剛好被改回)。
還原後要「強制全員重新登入」,就把一個時點記在 **Redis**(還原只動 PostgreSQL,不碰 Redis):
凡是簽發時間早於此時點的 session 一律失效。

Redis 不可用時 fail-open(不阻擋登入),並短暫快取結果,避免每次認證都打 Redis。
"""

import time

from redis import Redis

from app.core.config import settings

_KEY = "auth:min_session_iat"
_redis = Redis.from_url(
    settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
)

# 行程內快取:成功讀取快取 5 秒;Redis 不可用時 30 秒內不再重試(不拖慢認證)
_cache: dict[str, float] = {"val": 0.0, "exp": 0.0}


def min_issued_at() -> float:
    now = time.time()
    if now < _cache["exp"]:
        return _cache["val"]
    try:
        raw = _redis.get(_KEY)
        val = float(raw) if raw else 0.0
        _cache["val"], _cache["exp"] = val, now + 5
        return val
    except Exception:  # noqa: BLE001 - Redis 不可用不該擋住登入
        _cache["val"], _cache["exp"] = 0.0, now + 30
        return 0.0


def force_logout_all() -> None:
    """把「最小有效簽發時間」設為現在:所有既有 session 立即失效。"""
    try:
        _redis.set(_KEY, str(time.time()))
        _cache["exp"] = 0.0  # 使本行程快取失效,立即生效
    except Exception:  # noqa: BLE001
        return
    # 立即落盤:預設 RDB 快照條件下這個單一 key 可能一小時內都未持久化,
    # 若還原後 Redis 隨即崩潰,epoch 遺失會讓舊 cookie 復活。盡力而為,失敗不擋。
    try:
        _redis.bgsave()
    except Exception:  # noqa: BLE001 - 落盤失敗不影響強制登出本身
        pass
