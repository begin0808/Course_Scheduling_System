"""認證 API:登入、登出、目前使用者、變更密碼。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import COOKIE_NAME, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_session_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, UserOut

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_max_age_seconds,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = db.scalar(select(User).where(User.username == body.username))
    now = datetime.now(UTC)

    if user is None:
        # 不透露帳號是否存在
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")

    # 部分資料庫(如 SQLite)回傳 naive datetime,統一視為 UTC 再比較
    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)

    if locked_until is not None and locked_until > now:
        remaining = int((locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(status.HTTP_423_LOCKED, f"帳號已鎖定,請於約 {remaining} 分鐘後再試")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "帳號已停用,請洽系統管理員")

    if not verify_password(body.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_attempts = 0
            db.commit()
            raise HTTPException(
                status.HTTP_423_LOCKED,
                f"連續登入失敗,帳號已鎖定 {settings.lockout_minutes} 分鐘",
            )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")

    # 登入成功:清除失敗計數與鎖定
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    _set_session_cookie(response, user.id)
    return UserOut.from_model(user)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_model(user)


@router.post("/change-password", response_model=UserOut)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密碼錯誤")
    if len(body.new_password) < settings.min_password_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"新密碼至少需 {settings.min_password_length} 個字元"
        )
    if body.new_password == body.old_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密碼不可與原密碼相同")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    _set_session_cookie(response, user.id)  # 重新簽發 session
    return UserOut.from_model(user)
