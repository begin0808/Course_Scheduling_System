"""帳號與角色管理(v1.3.1)。

起因(使用者來信):教學組長、教務主任的帳號畫面上無處可設,填了「行政職稱」登入後仍是教師。
"""

import pytest

from app.models.basedata import Teacher
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def admin(env):
    client, db = env
    me = make_user(db, "root", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "root", "password": PW})
    return client, db, me


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _user(client, username):
    return next(u for u in client.get("/api/users").json() if u["username"] == username)


def test_only_admins_can_manage_accounts(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    _login(client, "s", PW)
    assert client.get("/api/users").status_code == 403
    r = client.post("/api/users", json={"username": "x", "roles": ["scheduler"]})
    assert r.status_code == 403


def test_create_a_scheduler_account_who_must_change_password_first(admin):
    client, _db, _ = admin
    r = client.post("/api/users", json={
        "username": "chen", "display_name": "陳組長", "password": "temp12345",
        "roles": ["scheduler"]})
    assert r.status_code == 201, r.text
    assert r.json()["roles"] == ["scheduler"] and r.json()["must_change_password"] is True

    client.post("/api/auth/logout")
    me = _login(client, "chen", "temp12345").json()
    assert "scheduler" in me["roles"] and me["must_change_password"] is True


def test_duplicate_username_and_bad_roles_are_rejected(admin):
    client, _db, _ = admin
    r = client.post("/api/users", json={"username": "root", "roles": ["director"]})
    assert r.status_code == 409
    r = client.post("/api/users", json={"username": "t", "roles": ["teacher"]})
    assert r.status_code == 400 and "教師身分" in r.json()["detail"]
    assert client.post("/api/users", json={"username": "t", "roles": []}).status_code == 422


def test_teacher_account_can_also_become_the_scheduler(admin):
    """組長本身是教師:同一個帳號加上教學組長,教師身分與綁定的教師資料都保留。"""
    client, db, _ = admin
    sid = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()["id"]
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    client.post(f"/api/teachers/{teacher['id']}/account",
                json={"username": "wang", "password": "teach12345"})

    u = _user(client, "wang")
    assert u["roles"] == ["teacher"] and u["teacher_names"] == ["王老師"]
    r = client.put(f"/api/users/{u['id']}/roles", json={"roles": ["scheduler"]})
    assert r.status_code == 200
    assert r.json()["roles"] == ["scheduler", "teacher"]
    assert db.get(Teacher, teacher["id"]).user_id == u["id"]

    # 拿掉組長身分:回到純教師
    r = client.put(f"/api/users/{u['id']}/roles", json={"roles": []})
    assert r.json()["roles"] == ["teacher"]


def test_account_must_keep_at_least_one_role(admin):
    client, _db, _ = admin
    u = client.post("/api/users", json={"username": "d", "roles": ["director"]}).json()
    r = client.put(f"/api/users/{u['id']}/roles", json={"roles": []})
    assert r.status_code == 400 and "停用" in r.json()["detail"]


def test_cannot_lock_everyone_out(admin):
    """不能拿掉自己的系統管理員身分、不能停用自己;最後一個管理員也拿不掉。"""
    client, _db, me = admin
    r = client.put(f"/api/users/{me.id}/roles", json={"roles": ["scheduler"]})
    assert r.status_code == 409 and "自己" in r.json()["detail"]
    r = client.post(f"/api/users/{me.id}/active", json={"is_active": False})
    assert r.status_code == 409 and "自己" in r.json()["detail"]

    other = client.post("/api/users", json={"username": "admin2", "roles": ["admin"]}).json()
    # 有兩位管理員時,可以拿掉另一位的管理員身分
    r = client.put(f"/api/users/{other['id']}/roles", json={"roles": ["director"]})
    assert r.status_code == 200
    # 再加回來、停用自己以外的唯一另一位也可以
    client.put(f"/api/users/{other['id']}/roles", json={"roles": ["admin"]})
    r = client.post(f"/api/users/{other['id']}/active", json={"is_active": False})
    assert r.status_code == 200


def test_deactivated_account_cannot_log_in_until_reactivated(admin):
    client, _db, _ = admin
    u = client.post("/api/users", json={
        "username": "lin", "password": "temp12345", "roles": ["director"]}).json()
    r = client.post(f"/api/users/{u['id']}/active", json={"is_active": False})
    assert r.json()["is_active"] is False
    client.post("/api/auth/logout")
    assert _login(client, "lin", "temp12345").status_code != 200
    _login(client, "root", PW)
    client.post(f"/api/users/{u['id']}/active", json={"is_active": True})
    client.post("/api/auth/logout")
    assert _login(client, "lin", "temp12345").status_code == 200


def test_reset_password_forces_a_change_and_ends_the_old_session(admin):
    client, _db, me = admin
    u = client.post("/api/users", json={
        "username": "lee", "password": "temp12345", "roles": ["scheduler"]}).json()
    r = client.post(f"/api/users/{u['id']}/reset-password", json={"password": "again12345"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    client.post("/api/auth/logout")
    assert _login(client, "lee", "temp12345").status_code != 200
    assert _login(client, "lee", "again12345").status_code == 200
    # 自己的密碼不從這裡改
    client.post("/api/auth/logout")
    _login(client, "root", PW)
    assert client.post(f"/api/users/{me.id}/reset-password", json={}).status_code == 409
    # 太短的密碼
    r = client.post(f"/api/users/{u['id']}/reset-password", json={"password": "123"})
    assert r.status_code == 400


def test_rename(admin):
    client, _db, _ = admin
    u = client.post("/api/users", json={"username": "x1", "roles": ["director"]}).json()
    assert u["display_name"] == "x1"
    r = client.patch(f"/api/users/{u['id']}", json={"display_name": "林主任"})
    assert r.json()["display_name"] == "林主任"
