"""認證與授權的 FastAPI 依賴。

三個層級:
- get_current_user:僅需登入(供 /me、改密碼、登出使用,允許 must_change_password 者)
- get_active_user:已登入且已完成必要改密(功能性 API 應依賴此)
- require_roles(*roles):在 get_active_user 之上再檢查角色;admin 為超級使用者通過所有檢查
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import password_fingerprint, read_session_token, session_issued_at
from app.core.session_epoch import min_issued_at
from app.models.user import Role, User

COOKIE_NAME = "session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登入")
    payload = read_session_token(token, settings.session_max_age_seconds)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已過期,請重新登入"
        )
    user = db.get(User, payload["uid"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="帳號無效")
    # 密碼指紋不符表示密碼已變更,舊 session 一律失效
    if payload.get("pv") != password_fingerprint(user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效,請重新登入"
        )
    # 全域強制重新登入(如資料庫還原後):簽發時間早於門檻的 session 失效
    epoch = min_issued_at()
    if epoch > 0:
        issued = session_issued_at(token, settings.session_max_age_seconds)
        if issued is not None and issued < epoch:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="系統已還原或重設,請重新登入",
            )
    return user


def get_active_user(user: User = Depends(get_current_user)) -> User:
    """已登入且無待處理的強制改密。功能性 API 應依賴此。"""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="請先變更密碼",
            headers={"X-Reason": "must_change_password"},
        )
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """回傳一個檢查角色的依賴。admin 一律通過。"""
    allowed = {r.value for r in roles}

    def checker(user: User = Depends(get_active_user)) -> User:
        names = user.role_names
        if Role.admin.value in names or allowed & names:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="權限不足")

    return checker
