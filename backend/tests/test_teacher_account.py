"""教師帳號綁定與聯絡資訊測試。對應 M2-0 驗收標準。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role, User
from app.services.teachers import current_teacher
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def sched(env):
    """已登入教學組長 + 一個學期。回傳 (client, semester_id, db)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    return client, sem["id"], db


def _make_teacher_account(db, username: str) -> int:
    return make_user(db, username, PW, roles=[Role.teacher]).id


# ── 聯絡資訊 ──────────────────────────
def test_contact_fields_crud(sched):
    client, sid, _ = sched
    r = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老師", "email": "wang@example.edu.tw", "phone": "0912345678",
              "line_id": "wang_line"},
    )
    assert r.status_code == 201
    t = r.json()
    assert t["email"] == "wang@example.edu.tw"
    assert t["phone"] == "0912345678"
    assert t["line_id"] == "wang_line"
    # 更新聯絡資訊
    r = client.patch(f"/api/teachers/{t['id']}", json={"name": "王老師", "email": "new@a.bc"})
    assert r.json()["email"] == "new@a.bc"
    assert r.json()["phone"] is None  # 未帶入 → 清空


def test_invalid_email_rejected(sched):
    """驗收④:Email 格式錯誤回報錯誤。"""
    client, sid, _ = sched
    r = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老師", "email": "not-an-email"}
    )
    assert r.status_code == 422


def test_empty_email_becomes_null(sched):
    client, sid, _ = sched
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師", "email": ""})
    assert r.status_code == 201
    assert r.json()["email"] is None


# ── 帳號綁定 ──────────────────────────
def test_bind_account_success(sched):
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": uid})
    assert r.status_code == 201
    assert r.json()["user_id"] == uid


def test_bind_nonexistent_account_400(sched):
    client, sid, _ = sched
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": 99999})
    assert r.status_code == 400


def test_bind_same_account_twice_409(sched):
    """驗收③:同帳號在同學期綁第二位教師 → 409。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    assert client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": uid}
    ).status_code == 201
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "李老師", "user_id": uid})
    assert r.status_code == 409


def test_rebind_same_teacher_ok(sched):
    """同一教師重存自己已綁的帳號不應被當成衝突。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": uid}
    ).json()
    r = client.patch(f"/api/teachers/{t['id']}", json={"name": "王老師", "user_id": uid})
    assert r.status_code == 200
    assert r.json()["user_id"] == uid


def test_bindable_accounts_excludes_bound(sched):
    client, sid, db = sched
    u1 = _make_teacher_account(db, "wang001")
    u2 = _make_teacher_account(db, "lee001")
    # 綁定 u1 給某教師
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": u1})
    avail = client.get(f"/api/teachers/bindable-accounts?semester_id={sid}").json()
    ids = {a["id"] for a in avail}
    assert u2 in ids and u1 not in ids


def test_bindable_accounts_includes_current_in_edit(sched):
    client, sid, db = sched
    u1 = _make_teacher_account(db, "wang001")
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": u1}
    ).json()
    # 編輯情境:帶 current_teacher_id → 應含目前綁定的 u1
    avail = client.get(
        f"/api/teachers/bindable-accounts?semester_id={sid}&current_teacher_id={t['id']}"
    ).json()
    assert u1 in {a["id"] for a in avail}


# ── 事後補開帳號(#9)與重設密碼(#10)──────────
def test_create_account_for_existing_teacher(sched):
    """匯入時沒建帳號的老師,事後可以直接補:建好即綁定,且首次登入必須改密碼。"""
    client, sid, db = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    assert t["user_id"] is None

    r = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang001"})
    assert r.status_code == 201, r.json()
    acc = r.json()
    assert acc["username"] == "wang001" and acc["must_change_password"] is True
    assert acc["display_name"] == "王老師"
    assert client.get(f"/api/teachers?semester_id={sid}").json()[0]["user_id"] == acc["id"]

    # 新帳號用預設密碼登入得了(密碼未指定時用部署設定的預設值)
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "changeme"}
    ).status_code == 200


def test_create_account_rejects_duplicate_username_and_second_account(sched):
    client, sid, db = sched
    _make_teacher_account(db, "wang001")
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()

    dup = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang001"})
    assert dup.status_code == 409 and "已存在" in dup.json()["detail"]

    assert client.post(
        f"/api/teachers/{t['id']}/account",
        json={"username": "wang002", "password": "teacherpw123"},
    ).status_code == 201
    again = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang003"})
    assert again.status_code == 409 and "已綁定" in again.json()["detail"]


def test_create_account_rejects_short_password(sched):
    client, sid, _ = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    r = client.post(
        f"/api/teachers/{t['id']}/account", json={"username": "wang001", "password": "short"}
    )
    assert r.status_code == 400 and "至少" in r.json()["detail"]


def test_reset_teacher_password(sched):
    """重設後:新密碼可登入、舊密碼不行,且對方下次登入要自行改密碼。"""
    client, sid, db = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    client.post(
        f"/api/teachers/{t['id']}/account",
        json={"username": "wang001", "password": "oldpassword1"},
    )

    r = client.post(
        f"/api/teachers/{t['id']}/account/reset-password", json={"password": "newpassword1"}
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is True

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "oldpassword1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "newpassword1"}
    ).status_code == 200


def test_reset_password_refuses_non_teacher_account(sched):
    """綁定的帳號若不只是教師角色(例如兼任組長),這條路不給改,避免越權。"""
    client, sid, db = sched
    boss = make_user(db, "boss", PW, roles=[Role.teacher, Role.scheduler])
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "主任老師", "user_id": boss.id}
    ).json()
    r = client.post(f"/api/teachers/{t['id']}/account/reset-password", json={})
    assert r.status_code == 403 and "系統管理員" in r.json()["detail"]


def test_reset_password_without_account_is_404(sched):
    client, sid, _ = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"}).json()
    r = client.post(f"/api/teachers/{t['id']}/account/reset-password", json={})
    assert r.status_code == 404 and "尚未綁定" in r.json()["detail"]


# ── current_teacher helper ──────────────
def test_current_teacher_helper(sched):
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師", "user_id": uid})
    user = db.get(User, uid)
    t = current_teacher(db, user, sid)
    assert t is not None and t.name == "王老師"
    # 未綁定學期回 None
    assert current_teacher(db, user, 99999) is None


# ── Excel 匯入綁定 ──────────────────────
def _make_xlsx(rows: list[list], ncols: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append(["表頭"] * ncols)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_teachers(client, sid, rows, ncols=11, create_accounts=True):
    content = _make_xlsx(rows, ncols)
    url = f"/api/import/teachers?semester_id={sid}"
    if create_accounts:
        url += "&create_accounts=true"
    return client.post(url, files={"file": ("t.xlsx", content, XLSX_MIME)})


def test_import_binds_account(sched):
    """驗收①:匯入教師勾建立帳號 → user_id 正確綁定;含聯絡欄位。"""
    client, sid, _ = sched
    rows = [
        ["王小明", "1234", "", 20, "", "", "否", "wang001", "wang@a.bc", "0911", "wl"],
        ["李小華", "5678", "", 18, "", "", "否", "lee001", "", "", ""],
    ]
    r = _upload_teachers(client, sid, rows)
    assert r.json()["imported"] == 2
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert wang["user_id"] is not None
    assert wang["email"] == "wang@a.bc"
    assert wang["phone"] == "0911"
    # 綁定帳號可用預設密碼登入
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"username": "wang001", "password": "changeme"})
    assert login.status_code == 200


def test_import_invalid_email_zero_write(sched):
    client, sid, _ = sched
    rows = [["王小明", "", "", "", "", "", "", "", "壞掉的email", "", ""]]
    body = _upload_teachers(client, sid, rows, create_accounts=False).json()
    assert body["imported"] == 0
    assert any("Email" in e for e in body["errors"])
    assert client.get(f"/api/teachers?semester_id={sid}").json() == []


# ── 開新學期複製保留綁定 ──────────────
def test_copy_preserves_binding_and_contact(sched):
    """驗收②:複製後新學期教師仍綁同一帳號、聯絡資訊完整。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老師", "user_id": uid, "email": "wang@a.bc", "phone": "0911"},
    )
    r = client.post(
        f"/api/semesters/{sid}/copy",
        json={"academic_year": 116, "term": 1, "grade_promotion": False},
    )
    assert r.status_code == 201
    nid = r.json()["id"]
    nt = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert nt["user_id"] == uid
    assert nt["email"] == "wang@a.bc"
    assert nt["phone"] == "0911"
