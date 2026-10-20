"""重設系統管理員密碼的指令(v1.3.2)。

起因(使用者來信):先啟動過一次才改 `.env` 的密碼,管理員帳號早已依舊密碼建立,
怎麼登都進不去、接著被鎖 15 分鐘。以前只能刪資料重裝或還原備份。
"""

import io
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import verify_password
from app.models.audit import AuditLog
from app.models.user import Role
from app.scripts.reset_admin import ResetError, reset_admin_password, run, temp_password
from tests.conftest import make_user

PW = "password123"


def test_locked_out_admin_can_log_in_with_the_temp_password_and_must_change_it(env):
    client, db = env
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert r.status_code == 423  # 已被鎖

    temp = reset_admin_password(db, "admin")

    db.refresh(admin)
    assert admin.locked_until is None and admin.failed_login_attempts == 0
    r = client.post("/api/auth/login", json={"username": "admin", "password": temp})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    old = client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert old.status_code == 401


def test_reset_ends_existing_sessions(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert client.get("/api/auth/me").status_code == 200
    reset_admin_password(db, "admin")
    assert client.get("/api/auth/me").status_code == 401


def test_deactivated_admin_is_enabled_again(db):
    admin = make_user(db, "admin", PW, roles=[Role.admin])
    admin.is_active = False
    admin.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()
    temp = reset_admin_password(db, "admin")
    assert admin.is_active is True
    assert verify_password(temp, admin.password_hash)


def test_unknown_username_lists_the_admin_accounts(db):
    make_user(db, "root", PW, roles=[Role.admin])
    make_user(db, "boss", PW, roles=[Role.admin, Role.director])
    make_user(db, "s", PW, roles=[Role.scheduler])
    with pytest.raises(ResetError, match="找不到帳號「admin」。系統管理員帳號有:boss、root"):
        reset_admin_password(db, "admin")


def test_only_admin_accounts_can_be_reset(db):
    s = make_user(db, "s", PW, roles=[Role.scheduler])
    with pytest.raises(ResetError, match="不是系統管理員帳號"):
        reset_admin_password(db, "s")
    assert verify_password(PW, s.password_hash)


def test_temp_password_is_plain_letters_and_digits():
    for _ in range(50):
        p = temp_password()
        assert len(p) == 12 and p.isalnum() and p.isascii()
        assert not set(p) & set("0O1lI")


def test_command_prints_the_temp_password_and_records_it(db):
    make_user(db, "admin", PW, roles=[Role.admin])
    out, err = io.StringIO(), io.StringIO()
    assert run(db, [], out, err) == 0
    temp = out.getvalue().split("臨時密碼:")[1].split()[0]
    assert len(temp) == 12
    log = db.query(AuditLog).one()
    assert (log.action, log.username) == ("reset_admin_password", "主機指令")
    assert temp not in log.detail

    out, err = io.StringIO(), io.StringIO()
    assert run(db, ["--username", "nobody"], out, err) == 1
    assert "找不到帳號「nobody」" in err.getvalue() and out.getvalue() == ""
