"""FastAPI 應用程式進入點。"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    assignments,
    audit,
    auth,
    backups,
    basedata,
    exports,
    health,
    imports,
    leaves,
    notifications,
    semesters,
    solver,
    substitution_log,
    substitution_stats,
    substitutions,
    timetables,
    wizard,
)
from app.api import (
    settings as settings_api,
)
from app.core.config import settings
from app.services.users import ensure_admin

logger = logging.getLogger(__name__)


# 啟動時 worker-ops 可能還在起(compose 是平行啟動的),故給它一段寬限期再判定。
OPS_CHECK_RETRIES = 6
OPS_CHECK_INTERVAL = 2.0


async def _warn_if_no_ops_worker() -> None:
    """背景檢查 ops 佇列有沒有 worker 在守,沒有就在啟動 log 講清楚。

    升級只換映像、沒更新 docker-compose.yml 的話,worker-ops 根本不存在;此時匯出/備份
    會失敗(那還算吵),而每日自動備份是**靜默**停擺的——沒人會發現,直到需要那份備份的
    那一天。不阻塞啟動,也不在冷啟動的頭幾秒就誤報。
    """
    try:
        from app.workers.queue import OPS_WORKER_MISSING, ops_worker_available

        for _ in range(OPS_CHECK_RETRIES):
            await asyncio.sleep(OPS_CHECK_INTERVAL)
            if await asyncio.to_thread(ops_worker_available):
                return
        logger.warning(OPS_WORKER_MISSING)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - Redis 尚未就緒等情況不該影響 api 運作
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 啟動時:若系統尚無任何使用者,依 .env 建立初始管理員
    ensure_admin()
    check = asyncio.create_task(_warn_if_no_ops_worker())
    yield
    check.cancel()


app = FastAPI(
    title=settings.app_name,
    description="開源免費的排課與調代課系統 API",
    version="0.1.0",
    # 正式部署預設關閉(見 settings.api_docs_enabled);None = 該路由不存在,回 404
    docs_url="/api/docs" if settings.api_docs_enabled else None,
    openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 所有 API 掛在 /api 前綴之下(Caddy 依此前綴分流)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(semesters.router, prefix="/api")
app.include_router(basedata.router, prefix="/api")
app.include_router(assignments.router, prefix="/api")
app.include_router(timetables.router, prefix="/api")
app.include_router(solver.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(leaves.router, prefix="/api")
app.include_router(substitutions.router, prefix="/api")
app.include_router(substitution_log.router, prefix="/api")
app.include_router(substitution_stats.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(backups.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(wizard.router, prefix="/api")
