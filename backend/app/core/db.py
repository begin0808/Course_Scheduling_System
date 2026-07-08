"""資料庫連線與 SQLAlchemy 基礎設定(SQLAlchemy 2.0 風格)。"""

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

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
    """FastAPI 依賴注入用的資料庫 session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
