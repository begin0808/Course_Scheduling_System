"""資料庫連線與 SQLAlchemy 基礎設定(SQLAlchemy 2.0 風格)。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM model 的基底。各 model 定義於 app/models/。"""


def get_db() -> Generator:
    """FastAPI 依賴注入用的資料庫 session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
