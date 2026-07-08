"""認證相關的請求/回應 schema。"""

from pydantic import BaseModel, Field

from app.models.user import User


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]
    must_change_password: bool

    @classmethod
    def from_model(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            roles=sorted(user.role_names),
            must_change_password=user.must_change_password,
        )
