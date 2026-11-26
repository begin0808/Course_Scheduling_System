"""重設系統管理員密碼的指令(v1.3.2;v1.7.0 起由主機管理者自己輸入新密碼)。

起因(使用者來信):先啟動過一次才改 `.env` 的密碼,管理員帳號早已依舊密碼建立,
怎麼登都進不去、接著被鎖 15 分鐘。以前只能刪資料重裝或還原備份。
"""

import io
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import verify_password
from app.models.audit import AuditLog
from app.models.user import Role
from app.scripts.reset_admin import ResetError, reset_admin_password, run
from tests.conftest import make_user

PW = "password123"
NEW = "brand-new-pass"


def answers(*typed: str):
    """模擬主機管理者依序輸入的內容(getpass 的替身),並記下提示文字。"""
    queue = list(typed)
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0)

    ask.prompts = prompts  # type: ignore[attr-defined]
    return ask


def test_locked_out_admin_can_log_in_with_the_typed_password(env):
    client, db = env
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert r.status_code == 423  # 已被鎖

    reset_admin_password(db, "admin", NEW)

    db.refresh(admin)
    assert admin.locked_until is None and admin.failed_login_attempts == 0
    r = client.post("/api/auth/login", json={"username": "admin", "password": NEW})
    assert r.status_code == 200
    # 密碼是自己挑的,不必再強迫改一次
    assert r.json()["must_change_password"] is False
    old = client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert old.status_code == 401


def test_reset_ends_existing_sessions(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert client.get("/api/auth/me").status_code == 200
    reset_admin_password(db, "admin", NEW)
    assert client.get("/api/auth/me").status_code == 401


def test_deactivated_admin_is_enabled_again(db):
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    admin.is_active = False
    admin.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()
    reset_admin_password(db, "admin", NEW)
    assert admin.is_active is True
    assert verify_password(NEW, admin.password_hash)


def test_unknown_username_lists_the_admin_accounts(db):
    make_user(db, "root", PW, roles=[Role.admin])
    make_user(db, "boss", PW, roles=[Role.admin, Role.director])
    make_user(db, "s", PW, roles=[Role.scheduler])
    with pytest.raises(ResetError, match="找不到帳號「admin」。系統管理員帳號有:boss、root"):
        reset_admin_password(db, "admin", NEW)


def test_only_admin_accounts_can_be_reset(db):
    s = make_user(db, "s", PW, roles=[Role.scheduler])
    with pytest.raises(ResetError, match="不是系統管理員帳號"):
        reset_admin_password(db, "s", NEW)
    assert verify_password(PW, s.password_hash)


def test_command_asks_twice_and_never_prints_the_password(db):
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    out, err = io.StringIO(), io.StringIO()
    ask = answers(NEW, NEW)
    assert run(db, [], out, err, ask=ask) == 0
    assert len(ask.prompts) == 2 and "不會顯示" in ask.prompts[0]
    assert verify_password(NEW, admin.password_hash)
    assert NEW not in out.getvalue() + err.getvalue()
    assert "已重設「admin」的密碼" in out.getvalue()
    log = db.query(AuditLog).one()
    assert (log.action, log.username) == ("reset_admin_password", "主機指令")
    assert NEW not in log.detail


def test_command_rejects_short_or_mismatched_input_then_accepts(db):
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    out, err = io.StringIO(), io.StringIO()
    assert run(db, [], out, err, ask=answers("short", NEW, "typo-pass", NEW, NEW)) == 0
    assert "至少要 8 個字元" in err.getvalue() and "兩次輸入不一致" in err.getvalue()
    assert verify_password(NEW, admin.password_hash)


def test_command_gives_up_after_three_bad_tries_without_changing_anything(db):
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    out, err = io.StringIO(), io.StringIO()
    assert run(db, [], out, err, ask=answers("a", "b", "c")) == 1
    assert "沒有重設密碼" in err.getvalue()
    assert verify_password(PW, admin.password_hash)
    assert db.query(AuditLog).count() == 0


def test_command_with_unknown_username_does_not_ask(db):
    make_user(db, "admin", PW, roles=[Role.admin])
    out, err = io.StringIO(), io.StringIO()
    ask = answers()
    assert run(db, ["--username", "nobody"], out, err, ask=ask) == 1
    assert "找不到帳號「nobody」" in err.getvalue() and out.getvalue() == ""
    assert ask.prompts == []
