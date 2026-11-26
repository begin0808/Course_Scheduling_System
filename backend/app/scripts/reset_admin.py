"""重設系統管理員密碼(v1.3.2;v1.7.0 改為主機管理者自己輸入新密碼)。

忘了密碼、或第一次就登不進去時,不必刪資料、也不必還原備份。

起因(使用者來信):照手冊手動安裝,先啟動過一次才改 `.env` 的密碼。管理員帳號只在系統
**第一次啟動**時依 `.env` 建立,之後改 `.env` 不會生效,結果怎麼登都是「帳號或密碼錯誤」,
接著被鎖 15 分鐘。

做法:執行時請主機管理者輸入新密碼兩次(輸入時不顯示),同時解除登入鎖定、重新啟用帳號。
v1.6 以前是產生臨時密碼印在畫面上;數發部源碼檢測把「密碼出現在輸出」列為風險,
v1.7.0 起改成自己輸入,畫面與紀錄都不會出現密碼。密碼一換,原本各裝置的登入都會失效。
只能重設**系統管理員**帳號,其他帳號由系統管理員登入後到「帳號管理」重設。

用法(在系統資料夾執行,不要加 -T,才能輸入密碼):
    docker compose exec api python -m app.scripts.reset_admin
    docker compose exec api python -m app.scripts.reset_admin --username 其他管理員帳號
"""

import argparse
import getpass
import sys
from collections.abc import Callable
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_TRIES = 3


class ResetError(Exception):
    """找不到帳號或不是系統管理員。"""


def admin_problem(db: Session, username: str) -> str | None:
    """帳號不能重設時回傳給使用者看的原因;可以重設時回傳 None。"""
    from app.models.user import Role, User

    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        admins = sorted(
            u.username for u in db.scalars(select(User)) if Role.admin.value in u.role_names
        )
        hint = f"系統管理員帳號有:{'、'.join(admins)},請用 --username 指定。" if admins else ""
        return f"找不到帳號「{username}」。{hint}"
    if Role.admin.value not in user.role_names:
        return (
            f"「{username}」不是系統管理員帳號。其他帳號請由系統管理員登入後到「帳號管理」重設密碼。"
        )
    return None


def reset_admin_password(db: Session, username: str, new_password: str) -> None:
    """把系統管理員帳號的密碼改成 new_password,並解除鎖定、重新啟用。"""
    from app.core.security import hash_password
    from app.models.audit import AuditLog
    from app.models.user import User

    problem = admin_problem(db, username)
    if problem:
        raise ResetError(problem)
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    user.password_hash = hash_password(new_password)
    # 密碼是主機管理者自己挑的,不必再強迫登入後改一次
    user.must_change_password = False
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_active = True
    db.add(AuditLog(
        user_id=None, username="主機指令", action="reset_admin_password",
        target_type="user", target_id=user.id, detail=f"重設「{user.username}」的密碼",
    ))
    db.commit()


def ask_new_password(ask: Callable[[str], str], err: TextIO, min_length: int) -> str | None:
    """請使用者輸入兩次新密碼;最多試 MAX_TRIES 次,都不合格回傳 None。"""
    for _ in range(MAX_TRIES):
        first = ask(f"新密碼(至少 {min_length} 個字元,輸入時不會顯示):")
        if len(first) < min_length:
            print(f"密碼至少要 {min_length} 個字元,請重新輸入。", file=err)
            continue
        if ask("再輸入一次確認:") != first:
            print("兩次輸入不一致,請重新輸入。", file=err)
            continue
        return first
    return None


def run(
    db: Session, argv: list[str], out: TextIO, err: TextIO,
    ask: Callable[[str], str] = getpass.getpass,
) -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.reset_admin", description="重設系統管理員密碼"
    )
    parser.add_argument(
        "--username", default=settings.admin_username,
        help=f"要重設的系統管理員帳號(預設 {settings.admin_username})",
    )
    args = parser.parse_args(argv)
    problem = admin_problem(db, args.username)
    if problem:
        print(problem, file=err)
        return 1

    print(f"要重設「{args.username}」的密碼,並解除登入鎖定。", file=out)
    chosen = ask_new_password(ask, err, settings.min_password_length)
    if chosen is None:
        print("沒有重設密碼(輸入不合格的次數太多),請重新執行。", file=err)
        return 1
    reset_admin_password(db, args.username, chosen)
    print(f"已重設「{args.username}」的密碼,並解除登入鎖定。", file=out)
    print(
        f"請用帳號 {args.username} 和剛才輸入的新密碼登入;原本已登入的裝置都要重新登入。",
        file=out,
    )
    print(".env 裡的 ADMIN_PASSWORD 只在系統第一次啟動時使用,不必修改。", file=out)
    return 0


def main() -> None:
    if not sys.stdin.isatty():
        print(
            "這個指令需要輸入新密碼,請直接在終端機執行(docker compose exec 不要加 -T):\n"
            "    docker compose exec api python -m app.scripts.reset_admin",
            file=sys.stderr,
        )
        sys.exit(2)

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
