"""FastAPI 應用程式進入點。"""

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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 啟動時:若系統尚無任何使用者,依 .env 建立初始管理員
    ensure_admin()
    yield


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
