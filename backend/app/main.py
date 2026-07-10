"""FastAPI 應用程式進入點。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    assignments,
    audit,
    auth,
    basedata,
    health,
    imports,
    semesters,
    solver,
    timetables,
    wizard,
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
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
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
app.include_router(audit.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(wizard.router, prefix="/api")
