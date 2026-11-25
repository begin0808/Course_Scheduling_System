"""v1.6.0 不再有公開的「系統預設密碼」:密碼留空時為每個帳號產生不同的隨機初始密碼。

先前匯入教師、補開帳號、重設密碼、帳號管理新增帳號,只要留空都用同一組寫在原始碼裡的
預設密碼;原始碼與手冊公開,老師第一次登入改密碼前,知道帳號的人就能搶先登入。
"""

import io
import secrets

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.core.config import Settings
from app.core.security import initial_password
from app.models.user import Role
from tests.conftest import make_user

PW = secrets.token_urlsafe(12)


@pytest.fixture
def sched(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    return client, sem["id"], db


@pytest.fixture
def admin(env):
    client, db = env
    make_user(db, "root", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "root", "password": PW})
    return client


def _login(client, username, password):
    client.post("/api/auth/logout")
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _teachers_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["欄名"] * 8)  # 範本前三列:欄名/說明/範例
    ws.append(["說明"] * 8)
    ws.append(["範例"] * 8)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_no_default_password_setting_anymore():
    assert not hasattr(Settings(_env_file=None), "default_import_password")
    a, gen_a = initial_password("")
    b, gen_b = initial_password("")
    assert a == gen_a and b == gen_b and a != b and len(a) == 12
    typed = secrets.token_urlsafe(9)
    assert initial_password(typed) == (typed, None)


def test_import_gives_each_teacher_a_different_password(sched):
    client, sid, _ = sched
    rows = [["王小明", "1234", "", 20, "", "", "否", "wang001"],
            ["李小華", "5678", "", 18, "", "", "否", "lee001"],
            ["陳大同", "9012", "", 18, "", "", "否", ""]]  # 沒填帳號的不建帳號
    r = client.post(f"/api/import/teachers?semester_id={sid}&create_accounts=true",
                    files={"file": ("t.xlsx", _teachers_xlsx(rows), XLSX_MIME)}).json()
    assert r["imported"] == 3
    accounts = r["accounts"]
    assert [(a["name"], a["username"]) for a in accounts] == [
        ("王小明", "wang001"), ("李小華", "lee001")]
    assert len({a["password"] for a in accounts}) == 2
    for a in accounts:
        me = _login(client, a["username"], a["password"]).json()
        assert me["must_change_password"] is True
    # 先前公開的預設密碼登不進去
    assert _login(client, "wang001", "changeme").status_code == 401


def test_import_without_accounts_returns_empty_list(sched):
    client, sid, _ = sched
    rows = [["王小明", "1234", "", 20, "", "", "否", "wang001"]]
    r = client.post(f"/api/import/teachers?semester_id={sid}",
                    files={"file": ("t.xlsx", _teachers_xlsx(rows), XLSX_MIME)}).json()
    assert r["imported"] == 1 and r["accounts"] == []


def test_teacher_account_and_reset_show_generated_password_once(sched):
    client, sid, _ = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    acc = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang001"}).json()
    first = acc["initial_password"]
    assert first and len(first) == 12
    # 之後查帳號狀態不會再看到密碼
    assert client.get(f"/api/teachers/{t['id']}/account").json()["initial_password"] is None

    reset = client.post(f"/api/teachers/{t['id']}/account/reset-password", json={}).json()
    second = reset["initial_password"]
    assert second and second != first
    # 組長自己輸入密碼時不回傳(組長已經知道)
    typed = secrets.token_urlsafe(9)
    again = client.post(f"/api/teachers/{t['id']}/account/reset-password",
                        json={"password": typed}).json()
    assert again["initial_password"] is None
    assert _login(client, "wang001", second).status_code == 401
    assert _login(client, "wang001", typed).status_code == 200


def test_account_management_generates_passwords(admin):
    client = admin
    u = client.post("/api/users", json={"username": "lee", "roles": ["scheduler"]}).json()
    first = u["initial_password"]
    assert first and len(first) == 12
    assert all(x.get("initial_password") is None for x in client.get("/api/users").json())

    reset = client.post(f"/api/users/{u['id']}/reset-password", json={}).json()
    assert reset["initial_password"] and reset["initial_password"] != first
    assert _login(client, "lee", reset["initial_password"]).json()["must_change_password"]
