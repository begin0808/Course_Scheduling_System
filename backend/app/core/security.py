"""密碼雜湊與 session token 簽署。

- 密碼:bcrypt(自帶 salt)
- session:itsdangerous 簽署的 timed token,放在 HttpOnly cookie,無需伺服器端 session 表
"""

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

# bcrypt 上限 72 bytes,超過會被截斷;此處明確截斷以避免新版 bcrypt 拋錯
_BCRYPT_MAX_BYTES = 72


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


_serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str, max_age: int) -> int | None:
    """驗證並解出 user_id;失效(過期/竄改/格式錯)一律回 None。"""
    try:
        data = _serializer.loads(token, max_age=max_age)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None
