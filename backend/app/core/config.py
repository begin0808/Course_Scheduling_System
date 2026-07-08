"""應用程式設定。所有設定值由環境變數提供(見專案根目錄 .env)。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 基本
    app_name: str = "排課與調代課系統"
    school_name: str = "示範學校"
    debug: bool = False
    # 學校所在時區,用於「今日/本週」等領域判定(見 architecture.md D6)
    tz: str = "Asia/Taipei"

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
    cookie_secure: bool = False  # 有 HTTPS 網域時設 True
    # 登入失敗鎖定
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # 新密碼最短長度
    min_password_length: int = 8

    # CORS(開發模式前端 dev server 來源)
    cors_origins: list[str] = ["http://localhost", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
