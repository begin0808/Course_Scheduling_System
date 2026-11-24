"""使用者相關服務:建立帳號、首次啟動建立管理員。"""

import logging
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password, temp_password
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
        configured = settings.admin_password.get_secret_value() if settings.admin_password else None
        password = configured or temp_password()
        create_user(
            db,
            username=settings.admin_username,
            password=password,
            roles=[Role.admin],
            display_name="系統管理員",
            must_change_password=True,
        )
        db.commit()
        if configured:
            logger.info("已建立初始管理員帳號:%s(首次登入需改密碼)", settings.admin_username)
        else:
            # 沒設 ADMIN_PASSWORD(v1.5.0 起程式不內建預設密碼):產生臨時密碼寫在啟動紀錄,
            # 架設的人用 docker compose logs api 查看;登入後強制更改
            logger.warning(
                "已建立初始管理員帳號:%s,臨時密碼:%s(.env 沒有設定 ADMIN_PASSWORD;"
                "登入後系統會要求立即改成新密碼)",
                settings.admin_username, password,
            )
