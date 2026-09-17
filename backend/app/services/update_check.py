"""系統版本與新版本提醒(v1.2.3)。

**為什麼要做。** 系統是各校自己架設的,新版發布後學校不會知道——只能靠作者一間間通知,
或學校自己去 GitHub 看。管理員登入「系統管理」就能看到「有新版本 vX.Y.Z」,並直接連到
更新內容與升級步驟。

**只提醒,不自動升級。** 升級要學校自己決定、先備份,這裡不碰容器也不拉映像。

**對外連線的界線:**
- 只送出一個讀取 GitHub 公開 Release 資訊的 GET,不帶任何學校資料。
- 結果快取在資料庫(`app_settings`),最多一天查一次;失敗(例如校內主機不能連外)也快取,
  不會每次開頁面都卡著等逾時。
- `.env` 設 `UPDATE_CHECK_ENABLED=false` 即完全不連外。

版本號由建置映像時的 `APP_VERSION` 注入(CI 在打版本標籤時帶入,如 `v1.2.3`);
自行從原始碼建置而沒帶時為 `dev`,此時照樣顯示最新版,但不判斷「是否較新」。
"""

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import settings as app_settings

logger = logging.getLogger(__name__)

CACHE_KEY = "update_check"
CHECK_INTERVAL = timedelta(hours=24)
# 「立即檢查」的最短間隔:避免連點把 GitHub 未登入 API 的額度(每小時 60 次)用光
MIN_FORCE_INTERVAL = timedelta(seconds=60)
TIMEOUT_SECONDS = 5

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(tag: str) -> tuple[int, int, int] | None:
    """「v1.2.3」→ (1, 2, 3)。預發布(v1.3.0-rc1)、dev、main-xxxx 等一律視為無法比較。"""
    m = _VERSION_RE.match(tag.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def current_version() -> str:
    return get_settings().app_version.strip() or "dev"


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    enabled: bool
    current: str
    latest: str = ""
    latest_url: str = ""
    published_at: str = ""
    checked_at: str = ""
    update_available: bool = False
    error: str = ""  # 最近一次查詢失敗的原因(給人看的);成功時為空


def _now() -> datetime:
    return datetime.now(UTC)


def _fetch_latest(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Course-Scheduling-System/{current_version()}",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 - 固定 https URL
        data = json.load(resp)
    return {
        "latest": str(data.get("tag_name") or ""),
        "latest_url": str(data.get("html_url") or ""),
        "published_at": str(data.get("published_at") or ""),
    }


def _load_cache(db: Session) -> dict:
    raw = app_settings.get(db, CACHE_KEY)
    try:
        cache = json.loads(raw) if raw else {}
    except ValueError:
        cache = {}
    return cache if isinstance(cache, dict) else {}


def _checked_at(cache: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(cache["checked_at"])
    except (KeyError, TypeError, ValueError):
        return None


def status(db: Session, *, refresh: bool = False) -> UpdateStatus:
    """目前版本與最新版本。快取過期(或 `refresh` 且距上次超過一分鐘)才真的連外查詢。

    呼叫端負責 commit(查詢結果寫入快取)。
    """
    settings = get_settings()
    current = current_version()
    if not settings.update_check_enabled:
        return UpdateStatus(enabled=False, current=current)

    cache = _load_cache(db)
    last = _checked_at(cache)
    now = _now()
    stale = last is None or now - last >= CHECK_INTERVAL
    forced = refresh and (last is None or now - last >= MIN_FORCE_INTERVAL)
    if stale or forced:
        fresh: dict = {"checked_at": now.isoformat()}
        try:
            fresh.update(_fetch_latest(settings.update_check_url))
            fresh["error"] = ""
        except Exception as exc:  # noqa: BLE001 - 連不上外網是常態,不能讓系統管理頁壞掉
            logger.info("檢查新版本失敗:%s", exc)
            # 保留上次成功查到的版本,只更新失敗原因與時間
            fresh.update({k: cache.get(k, "") for k in ("latest", "latest_url", "published_at")})
            fresh["error"] = "無法連線到 GitHub 查詢最新版本(學校主機可能無法連外)"
        cache = fresh
        app_settings.set_value(db, CACHE_KEY, json.dumps(cache, ensure_ascii=False))
        db.flush()  # 同一個 session 內再讀快取要讀得到(否則會重複連外)

    latest = str(cache.get("latest", ""))
    cur_v, latest_v = parse_version(current), parse_version(latest)
    return UpdateStatus(
        enabled=True,
        current=current,
        latest=latest,
        latest_url=str(cache.get("latest_url", "")),
        published_at=str(cache.get("published_at", "")),
        checked_at=str(cache.get("checked_at", "")),
        update_available=bool(cur_v and latest_v and latest_v > cur_v),
        error=str(cache.get("error", "")),
    )
