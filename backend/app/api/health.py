"""健康檢查端點。供 Docker healthcheck 與部署驗證使用。"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """存活檢查:程序有回應即為 ok。"""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness() -> dict:
    """就緒檢查:確認資料庫可連線。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
