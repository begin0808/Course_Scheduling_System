"""重設系統管理員密碼(v1.3.2):忘了密碼、或第一次就登不進去時,不必刪資料、也不必還原備份。

起因(使用者來信):照手冊手動安裝,先啟動過一次才改 `.env` 的密碼。管理員帳號只在系統
**第一次啟動**時依 `.env` 建立,之後改 `.env` 不會生效,結果怎麼登都是「帳號或密碼錯誤」,
接著被鎖 15 分鐘。

做法:產生一組只含英文與數字的臨時密碼(避開 `.env` 裡 `$`、`#` 的問題,也不必把密碼打在
指令上而留在終端機紀錄),同時解除登入鎖定、重新啟用帳號。對方登入後必須立即改密碼;
密碼一換,原本各裝置的登入都會失效。只能重設**系統管理員**帳號,其他帳號由系統管理員登入後
到「帳號管理」重設。

用法(在系統資料夾執行):
    docker compose exec api python -m app.scripts.reset_admin
    docker compose exec api python -m app.scripts.reset_admin --username 其他管理員帳號
"""

import argparse
import secrets
import sys
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

# 不易看錯的字元:去掉 0/O、1/l/I
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_LENGTH = 12


class ResetError(Exception):
    """找不到帳號或不是系統管理員;訊息直接給使用者看。"""


def temp_password() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def reset_admin_password(db: Session, username: str, password: str | None = None) -> str:
    """把系統管理員帳號的密碼重設為臨時密碼並解除鎖定,回傳臨時密碼。"""
    from app.core.security import hash_password
    from app.models.audit import AuditLog
    from app.models.user import Role, User

    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        admins = sorted(
            u.username for u in db.scalars(select(User)) if Role.admin.value in u.role_names
        )
        hint = f"系統管理員帳號有:{'、'.join(admins)},請用 --username 指定。" if admins else ""
        raise ResetError(f"找不到帳號「{username}」。{hint}")
    if Role.admin.value not in user.role_names:
        raise ResetError(
            f"「{username}」不是系統管理員帳號。其他帳號請由系統管理員登入後到「帳號管理」重設密碼。"
        )
    temp = password or temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_active = True
    db.add(AuditLog(
        user_id=None, username="主機指令", action="reset_admin_password",
        target_type="user", target_id=user.id, detail=f"重設「{user.username}」的密碼",
    ))
    db.commit()
    return temp


def run(db: Session, argv: list[str], out: TextIO, err: TextIO) -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.reset_admin", description="重設系統管理員密碼"
    )
    parser.add_argument(
        "--username", default=settings.admin_username,
        help=f"要重設的系統管理員帳號(預設 {settings.admin_username})",
    )
    args = parser.parse_args(argv)
    try:
        temp = reset_admin_password(db, args.username)
    except ResetError as exc:
        print(str(exc), file=err)
        return 1
    print(f"已重設「{args.username}」的密碼,並解除登入鎖定。", file=out)
    print(f"臨時密碼:{temp}", file=out)
    print(
        f"請用帳號 {args.username} 和這組臨時密碼登入,系統會要求立即改成新密碼;"
        "原本已登入的裝置都要重新登入。",
        file=out,
    )
    print(".env 裡的 ADMIN_PASSWORD 只在系統第一次啟動時使用,不必修改。", file=out)
    return 0


def main() -> None:
    import app.models  # noqa: F401 - 載入全部 model,關聯才完整
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        code = run(db, sys.argv[1:], sys.stdout, sys.stderr)
    finally:
        db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
