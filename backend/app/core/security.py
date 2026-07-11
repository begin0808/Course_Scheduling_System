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


def password_fingerprint(password_hash: str) -> str:
    """由密碼雜湊取指紋(尾段)。改密碼後指紋改變,用來使既有 session 失效。"""
    return password_hash[-12:]


_serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def create_session_token(user_id: int, pv: str) -> str:
    """簽發 session token。pv 為密碼指紋,供改密後撤銷舊 session。"""
    return _serializer.dumps({"uid": user_id, "pv": pv})


def read_session_token(token: str, max_age: int) -> dict | None:
    """驗證並解出 token 內容 {"uid", "pv"};失效(過期/竄改/格式錯)一律回 None。"""
    try:
        data = _serializer.loads(token, max_age=max_age)
        if not isinstance(data, dict) or "uid" not in data:
            return None
        return data
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


def session_issued_at(token: str, max_age: int) -> float | None:
    """token 的簽發時間(unix 秒);用於全域強制重新登入(M5-2)。失效回 None。"""
    try:
        _data, ts = _serializer.loads(token, max_age=max_age, return_timestamp=True)
        return ts.timestamp()
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
