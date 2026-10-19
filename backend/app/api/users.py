"""帳號與角色管理(v1.3.1,限系統管理員)。

先前畫面上只建得出兩種帳號:安裝時的系統管理員,與從教師資料建立的教師帳號——
教學組長、教務主任的帳號無處可設,填了「行政職稱」登入後仍是教師(使用者來信詢問)。

- 新增帳號並指定角色(教學組長/教務主任/系統管理員)。
- 既有帳號加上或拿掉角色:組長本身多半也是教師,同一個帳號就能同時查自己的課表、又能排課。
  「教師」身分來自綁定的教師資料,這裡不改。
- 停用/啟用、重設密碼(對方下次登入必須自行改密碼;密碼指紋改變,既有登入狀態立即失效)。
- 不提供刪除:帳號連著請假、調代課等歷史紀錄,停用即可。

護欄:至少要留一個啟用中的系統管理員;不能停用自己、不能拿掉自己的系統管理員身分
(否則可能整套系統沒有人能管理)。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.config import settings
from app.core.db import get_db
from app.core.security import hash_password
from app.models.basedata import Teacher
from app.models.user import Role, User, UserRole

router = APIRouter(tags=["users"])

admin_only = require_roles(Role.admin)

# 可在這裡指派的角色;「教師」由綁定教師資料決定
MANAGED_ROLES = (Role.scheduler.value, Role.director.value, Role.admin.value)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]
    is_active: bool
    must_change_password: bool
    teacher_names: list[str] = []  # 綁定的教師資料(不同學期可能各一筆,姓名相同只列一次)


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)  # 空 = 使用預設密碼
    roles: list[str] = Field(min_length=1)


class RolesIn(BaseModel):
    roles: list[str]  # 只含可指派的角色;教師身分不受影響


class DisplayNameIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=128)


class ActiveIn(BaseModel):
    is_active: bool


def _out(db: Session, user: User) -> UserOut:
    names = db.scalars(
        select(Teacher.name).where(Teacher.user_id == user.id).distinct().order_by(Teacher.name)
    ).all()
    order = {r: i for i, r in enumerate((*MANAGED_ROLES[::-1], Role.teacher.value))}
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        roles=sorted(user.role_names, key=lambda r: order.get(r, 99)),
        is_active=user.is_active, must_change_password=user.must_change_password,
        teacher_names=list(names),
    )


def _get(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到帳號")
    return user


def _check_roles(roles: list[str]) -> set[str]:
    bad = [r for r in roles if r not in MANAGED_ROLES]
    if bad:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "只能指派教學組長、教務主任、系統管理員;教師身分由「教師」資料的登入帳號決定",
        )
    return set(roles)


def _password(raw: str) -> str:
    password = raw or settings.default_import_password
    if len(password) < settings.min_password_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"密碼至少需 {settings.min_password_length} 個字元")
    return password


def _active_admins(db: Session, exclude: int | None = None) -> int:
    stmt = (
        select(func.count(func.distinct(User.id)))
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == Role.admin.value, User.is_active.is_(True))
    )
    if exclude is not None:
        stmt = stmt.where(User.id != exclude)
    return int(db.scalar(stmt) or 0)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    users = db.scalars(select(User).order_by(User.username)).all()
    return [_out(db, u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateIn, db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """新增行政帳號(教學組長、教務主任、系統管理員)。對方第一次登入必須自行改密碼。"""
    roles = _check_roles(body.roles)
    username = body.username.strip()
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "請輸入登入帳號")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"登入帳號「{username}」已存在")
    user = User(
        username=username, password_hash=hash_password(_password(body.password)),
        display_name=body.display_name.strip() or username, must_change_password=True,
        roles=[UserRole(role=r) for r in sorted(roles)],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _out(db, user)


@router.put("/users/{user_id}/roles", response_model=UserOut)
def set_roles(
    user_id: int, body: RolesIn, db: Session = Depends(get_db), me: User = Depends(admin_only)
):
    """設定這個帳號的行政角色(教學組長/教務主任/系統管理員);教師身分保留不動。"""
    user = _get(db, user_id)
    wanted = _check_roles(body.roles)
    is_teacher = Role.teacher.value in user.role_names
    if not wanted and not is_teacher:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "至少要有一個角色;不再使用的帳號請改用「停用」")
    had_admin = Role.admin.value in user.role_names
    if had_admin and Role.admin.value not in wanted:
        if user.id == me.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "不能拿掉自己的系統管理員身分")
        if user.is_active and _active_admins(db, exclude=user.id) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "至少要保留一個啟用中的系統管理員")
    for r in list(user.roles):
        if r.role in MANAGED_ROLES and r.role not in wanted:
            user.roles.remove(r)
    for role in sorted(wanted - user.role_names):
        user.roles.append(UserRole(role=role))
    db.commit()
    db.refresh(user)
    return _out(db, user)


@router.patch("/users/{user_id}", response_model=UserOut)
def rename_user(
    user_id: int, body: DisplayNameIn, db: Session = Depends(get_db), _: User = Depends(admin_only)
):
    user = _get(db, user_id)
    user.display_name = body.display_name.strip()
    db.commit()
    db.refresh(user)
    return _out(db, user)


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: int, body: PasswordIn, db: Session = Depends(get_db), me: User = Depends(admin_only)
):
    """重設密碼;對方下次登入必須自行改密碼,目前的登入狀態會立即失效。"""
    user = _get(db, user_id)
    if user.id == me.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "自己的密碼請用右上角的「修改密碼」")
    user.password_hash = hash_password(_password(body.password))
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    db.refresh(user)
    return _out(db, user)


@router.post("/users/{user_id}/active", response_model=UserOut)
def set_active(
    user_id: int, body: ActiveIn, db: Session = Depends(get_db), me: User = Depends(admin_only)
):
    """停用(立刻無法登入,帳號與歷史紀錄都保留)或重新啟用。"""
    user = _get(db, user_id)
    if not body.is_active:
        if user.id == me.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "不能停用自己的帳號")
        if Role.admin.value in user.role_names and _active_admins(db, exclude=user.id) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "至少要保留一個啟用中的系統管理員")
        user.failed_login_attempts = 0
        user.locked_until = None
    user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return _out(db, user)
