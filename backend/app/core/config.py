"""應用程式設定。所有設定值由環境變數提供(見專案根目錄 .env)。"""

import logging
import secrets
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 已知不安全的 SECRET_KEY 值(程式碼預設 + .env.example 範例)。啟動時若仍是這些,
# 代表部署者沒設定——用隨機金鑰取代並警告,避免以公開金鑰簽署 session。
_INSECURE_SECRETS = {
    "dev-insecure-change-me",
    "please-change-this-to-a-random-secret",
    "",
}


def _is_real_domain(site_address: str) -> bool:
    """SITE_ADDRESS 是否為真實網域(而非內網 HTTP 的預設 :80/空)。"""
    s = site_address.strip()
    return bool(s) and s != ":80" and not s.startswith(":")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 基本
    app_name: str = "排課與調代課系統"
    school_name: str = "示範學校"
    debug: bool = False
    # 學校所在時區,用於「今日/本週」等領域判定(見 architecture.md D6)
    tz: str = "Asia/Taipei"
    # 排程器心跳間隔(秒);週期任務骨架用,M5-2 每日備份亦掛此排程器
    scheduler_heartbeat_seconds: int = 3600
    # 備份(M5-2):存放目錄(api 與 worker 共掛的 volume)、保留份數、每日自動備份時刻
    backup_dir: str = "/backups"
    backup_keep: int = 30
    backup_hour: int = 2  # 每日自動備份的小時(學校時區)

    # 資料庫與佇列
    database_url: str = "postgresql+psycopg://scheduler:scheduler@postgres:5432/scheduler"
    redis_url: str = "redis://redis:6379/0"

    # 首次啟動建立的管理員
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # 認證與 session
    # 用於簽署 session cookie;正式部署務必於 .env 設定隨機值
    secret_key: str = "dev-insecure-change-me"
    session_max_age_seconds: int = 60 * 60 * 8  # 登入有效時間,預設 8 小時
    # 站台位址(與 Caddy 共用同一 .env 變數):設為網域即代表走 HTTPS
    site_address: str = ""
    # cookie Secure 旗標。預設 False(內網 HTTP);SITE_ADDRESS 為網域時自動 True(見 _harden)
    cookie_secure: bool = False
    # 登入失敗鎖定
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # 新密碼最短長度
    min_password_length: int = 8
    # 匯入教師並建立帳號時的預設密碼(首次登入強制更改)
    default_import_password: str = "changeme"

    # CORS(開發模式前端 dev server 來源)
    cors_origins: list[str] = ["http://localhost", "http://localhost:5173"]

    @model_validator(mode="after")
    def _harden(self) -> "Settings":
        # A:SECRET_KEY 仍為預設/範例值 → 換隨機金鑰,避免以公開金鑰簽署 session
        if self.secret_key in _INSECURE_SECRETS:
            self.secret_key = secrets.token_hex(32)
            logger.warning(
                "未設定 SECRET_KEY,已改用隨機金鑰(重啟會使所有登入失效);"
                "請於 .env 設定固定的 SECRET_KEY(例:openssl rand -hex 32)。"
            )
        # B:設了網域(走 HTTPS)但未顯式指定 COOKIE_SECURE → 自動開啟 Secure 旗標
        if "cookie_secure" not in self.model_fields_set and _is_real_domain(self.site_address):
            self.cookie_secure = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
