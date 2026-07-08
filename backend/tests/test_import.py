"""Excel 匯入測試。對應 M1-3 驗收標準。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def scheduler_env(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    return client, sem["id"]


def make_xlsx(data_rows: list[list], ncols: int = 8) -> bytes:
    """建立含 3 列表頭(欄名/說明/範例)+ 資料列的 xlsx。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["欄名"] * ncols)
    ws.append(["說明"] * ncols)
    ws.append(["範例"] * ncols)
    for r in data_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, entity, sid, data_rows, ncols=8, create_accounts=False):
    content = make_xlsx(data_rows, ncols)
    url = f"/api/import/{entity}?semester_id={sid}"
    if create_accounts:
        url += "&create_accounts=true"
    return client.post(url, files={"file": ("t.xlsx", content, XLSX_MIME)})


def test_download_template(scheduler_env):
    client, _ = scheduler_env
    for entity in ("subjects", "teachers", "classes"):
        r = client.get(f"/api/import/templates/{entity}")
        assert r.status_code == 200
        assert r.headers["content-type"] == XLSX_MIME
        assert len(r.content) > 0


def test_import_subjects_ok(scheduler_env):
    client, sid = scheduler_env
    rows = [["數學", "數學領域", "普通教室", 1], ["物理", "自然", "專科教室", 2]]
    r = upload(client, "subjects", sid, rows, ncols=4)
    assert r.status_code == 200
    assert r.json() == {"imported": 2, "errors": []}
    assert len(client.get(f"/api/subjects?semester_id={sid}").json()) == 2


def test_import_subjects_invalid_room_type_zero_write(scheduler_env):
    """驗收②:錯誤回報列號,資料庫零寫入。"""
    client, sid = scheduler_env
    rows = [["數學", "", "普通教室", 1], ["體育", "", "操場外", 1]]  # 第 5 列場地類型無效
    r = upload(client, "subjects", sid, rows, ncols=4)
    body = r.json()
    assert body["imported"] == 0
    assert any("第 5 列" in e and "場地類型" in e for e in body["errors"])
    # 零寫入:連合法的第 4 列也未寫入
    assert client.get(f"/api/subjects?semester_id={sid}").json() == []


def test_import_teachers_with_accounts(scheduler_env):
    """驗收①:匯入教師、建立帳號、任教科目關聯。"""
    client, sid = scheduler_env
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "數學"})
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "物理"})
    rows = [
        ["王小明", "1234", "數學、物理", 20, "教學組長", 4, "否", "wang001"],
        ["李小華", "5678", "數學", 18, "", "", "是", "lee001"],
    ]
    r = upload(client, "teachers", sid, rows, create_accounts=True)
    assert r.json()["imported"] == 2
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert {s["name"] for s in wang["subjects"]} == {"數學", "物理"}
    # 帳號已建立,可用預設密碼登入(首登需改密)
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"username": "wang001", "password": "changeme"})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


def test_import_teachers_duplicate_name_id4(scheduler_env):
    client, sid = scheduler_env
    rows = [["王小明", "1234", "", "", "", "", "", ""], ["王小明", "1234", "", "", "", "", "", ""]]
    r = upload(client, "teachers", sid, rows)
    body = r.json()
    assert body["imported"] == 0
    assert any("重複" in e for e in body["errors"])
    assert client.get(f"/api/teachers?semester_id={sid}").json() == []


def test_import_teachers_unknown_subject(scheduler_env):
    client, sid = scheduler_env
    rows = [["王小明", "", "不存在的科目", "", "", "", "", ""]]
    body = upload(client, "teachers", sid, rows).json()
    assert body["imported"] == 0
    assert any("科目" in e for e in body["errors"])


def test_import_classes_with_homeroom(scheduler_env):
    """驗收③相關:班級匯入,導師以姓名對應。"""
    client, sid = scheduler_env
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "陳老師"})
    rows = [["1", "甲", "技術型高中", "機械科", "陳老師", 35]]
    r = upload(client, "classes", sid, rows, ncols=6)
    assert r.json()["imported"] == 1
    cu = client.get(f"/api/class-units?semester_id={sid}").json()[0]
    assert cu["department"] == "機械科"
    assert cu["homeroom_teacher"]["name"] == "陳老師"


def test_import_classes_unknown_homeroom(scheduler_env):
    client, sid = scheduler_env
    rows = [["1", "甲", "國小", "", "查無此人", ""]]
    body = upload(client, "classes", sid, rows, ncols=6).json()
    assert body["imported"] == 0
    assert any("導師" in e for e in body["errors"])


def test_import_invalid_file_rejected(scheduler_env):
    client, sid = scheduler_env
    r = client.post(
        f"/api/import/subjects?semester_id={sid}",
        files={"file": ("bad.xlsx", b"not an excel file", XLSX_MIME)},
    )
    assert r.status_code == 400
