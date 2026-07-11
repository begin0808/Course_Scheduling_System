"""測試共用設定。

以 SQLite 記憶體資料庫建立獨立測試環境,並組出一個含 auth 路由與
兩個受保護測試路由(_protected、_scheduler)的 app,用來驗證 RBAC 依賴。
"""

from collections.abc import Iterable

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import (
    assignments,
    audit,
    auth,
    basedata,
    exports,
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
from app.core.auth import get_active_user, require_roles
from app.core.db import Base, get_db
from app.models.user import Role, User
from app.services.users import create_user


@pytest.fixture
def db():
    """乾淨的測試資料庫 session(不經 API)。給 fixtures builder 與服務層測試用。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def env():
    """回傳 (client, db) — client 打 API,db 供測試準備資料。共用同一 SQLite 連線。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    application = FastAPI()
    application.include_router(auth.router, prefix="/api/auth")
    application.include_router(semesters.router, prefix="/api")
    application.include_router(basedata.router, prefix="/api")
    application.include_router(assignments.router, prefix="/api")
    application.include_router(timetables.router, prefix="/api")
    application.include_router(solver.router, prefix="/api")
    application.include_router(exports.router, prefix="/api")
    application.include_router(audit.router, prefix="/api")
    application.include_router(imports.router, prefix="/api")
    application.include_router(wizard.router, prefix="/api")
    application.include_router(leaves.router, prefix="/api")
    application.include_router(substitutions.router, prefix="/api")
    application.include_router(substitution_log.router, prefix="/api")
    application.include_router(substitution_stats.router, prefix="/api")
    application.include_router(notifications.router, prefix="/api")
    application.include_router(settings_api.router, prefix="/api")

    @application.get("/api/_protected")
    def _protected(user: User = Depends(get_active_user)) -> dict:
        return {"user": user.username}

    @application.get("/api/_scheduler")
    def _scheduler(user: User = Depends(require_roles(Role.scheduler))) -> dict:
        return {"user": user.username}

    application.dependency_overrides[get_db] = override_get_db

    setup_db = TestSession()
    client = TestClient(application)
    try:
        yield client, setup_db
    finally:
        setup_db.close()
        Base.metadata.drop_all(engine)


def make_user(
    db: Session,
    username: str,
    password: str = "password123",
    roles: Iterable[Role] = (),
    must_change_password: bool = False,
) -> User:
    user = create_user(
        db,
        username=username,
        password=password,
        roles=list(roles),
        must_change_password=must_change_password,
    )
    db.commit()
    return user
