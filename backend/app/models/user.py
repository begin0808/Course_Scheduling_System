"""帳號與角色 model。

一個 User 可有多個角色(RBAC);admin 為超級使用者,通過所有角色檢查。
teacher 角色的帳號日後(M1)以 nullable 的 teacher_id 綁定教師主檔。
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(enum.StrEnum):
    """系統角色。值即為資料庫與 API 使用的字串。"""

    admin = "admin"          # 系統管理員(超級使用者)
    director = "director"    # 教務主任
    scheduler = "scheduler"  # 教學組長
    teacher = "teacher"      # 教師


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 首次登入或被重設密碼後為 True,強制使用者改密碼後才能使用其他功能
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 認證來源:local(本地帳密)或未來的 oidc(教育雲端帳號)
    auth_provider: Mapped[str] = mapped_column(String(20), default="local")
    # 登入失敗鎖定機制
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def role_names(self) -> set[str]:
        return {r.role for r in self.roles}


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))

    user: Mapped["User"] = relationship(back_populates="roles")
