"""資料庫連線與 SQLAlchemy 基礎設定(SQLAlchemy 2.0 風格)。"""

import logging
from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# 統一約束/索引命名慣例,確保跨資料庫(PostgreSQL/SQLite)遷移可靠、可預測
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM model 的基底。各 model 定義於 app/models/。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db() -> Generator:
    """FastAPI 依賴注入用的資料庫 session。

    收尾的 `close()` 刻意吞掉例外:yield 依賴是在**回應送出後**才收尾,此時再擲出例外
    只會變成一段沒有請求可歸屬的 ASGI traceback,而使用者早已拿到(正確的)回應。
    唯一會走到這裡的情境是連線在請求期間被中止——資料庫剛被還原(pg_restore --clean
    會砍掉所有連線)、或 DBA 手動踢人。真正的失敗會在查詢當下就報錯,不會被這裡蓋掉。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            logger.warning("關閉資料庫 session 時連線已中止(多半是剛還原過資料庫)")
