"""認證與 RBAC 流程測試。對應 M0-2 驗收標準。"""

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


def test_login_success(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    resp = client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["roles"] == ["admin"]
    assert "session" in resp.cookies


def test_login_wrong_password(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(env):
    client, _ = env
    resp = client.post("/api/auth/login", json={"username": "ghost", "password": PW})
    assert resp.status_code == 401


def test_lockout_after_5_failures(env):
    client, db = env
    make_user(db, "u", PW, roles=[Role.teacher])

    def attempt(password: str) -> int:
        resp = client.post("/api/auth/login", json={"username": "u", "password": password})
        return resp.status_code

    # 前 4 次錯誤 → 401
    for _ in range(4):
        assert attempt("x") == 401
    # 第 5 次 → 觸發鎖定 423
    assert attempt("x") == 423
    # 鎖定期間即使密碼正確也被拒 423
    assert attempt(PW) == 423


def test_me_requires_auth(env):
    client, _ = env
    assert client.get("/api/auth/me").status_code == 401


def test_me_authenticated(env):
    client, db = env
    make_user(db, "scheduler1", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "scheduler1", "password": PW})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "scheduler1"


def test_logout_clears_session(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_protected_requires_auth(env):
    client, _ = env
    assert client.get("/api/_protected").status_code == 401


def test_must_change_password_blocks_then_allows(env):
    client, db = env
    make_user(db, "newbie", PW, roles=[Role.scheduler], must_change_password=True)
    login = client.post("/api/auth/login", json={"username": "newbie", "password": PW})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    # 尚未改密 → 功能性 API 403
    assert client.get("/api/_protected").status_code == 403
    # 改密後 → 可用
    chg = client.post(
        "/api/auth/change-password",
        json={"old_password": PW, "new_password": "brandnew456"},
    )
    assert chg.status_code == 200
    assert chg.json()["must_change_password"] is False
    assert client.get("/api/_protected").status_code == 200


def test_change_password_too_short(env):
    client, db = env
    make_user(db, "u", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "u", "password": PW})
    resp = client.post(
        "/api/auth/change-password", json={"old_password": PW, "new_password": "short"}
    )
    assert resp.status_code == 400


def test_change_password_wrong_old(env):
    client, db = env
    make_user(db, "u", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "u", "password": PW})
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "nope", "new_password": "brandnew456"},
    )
    assert resp.status_code == 400


def test_rbac_teacher_forbidden_on_scheduler(env):
    client, db = env
    make_user(db, "t", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert client.get("/api/_scheduler").status_code == 403


def test_rbac_scheduler_allowed(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    assert client.get("/api/_scheduler").status_code == 200


def test_rbac_admin_bypasses_role_check(env):
    client, db = env
    make_user(db, "admin", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin", "password": PW})
    # admin 未持有 scheduler 角色,但為超級使用者 → 允許
    assert client.get("/api/_scheduler").status_code == 200
