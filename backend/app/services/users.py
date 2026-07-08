"""使用者相關服務:建立帳號、首次啟動建立管理員。"""

import logging
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import Role, User, UserRole

logger = logging.getLogger("app.users")


def create_user(
    db: Session,
    username: str,
    password: str,
    roles: Iterable[Role],
    display_name: str = "",
    must_change_password: bool = True,
) -> User:
    """建立帳號並指派角色。呼叫端負責 commit。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        must_change_password=must_change_password,
        roles=[UserRole(role=r.value) for r in roles],
    )
    db.add(user)
    db.flush()
    return user


def ensure_admin() -> None:
    """系統首次啟動(尚無任何使用者)時,依 .env 建立管理員帳號。

    以「是否已有任何使用者」判斷,避免重複建立;預設要求首次登入改密碼。
    """
    with SessionLocal() as db:
        user_count = db.scalar(select(func.count()).select_from(User))
        if user_count and user_count > 0:
            return
        create_user(
            db,
            username=settings.admin_username,
            password=settings.admin_password,
            roles=[Role.admin],
            display_name="系統管理員",
            must_change_password=True,
        )
        db.commit()
        logger.info("已建立初始管理員帳號:%s(首次登入需改密碼)", settings.admin_username)
