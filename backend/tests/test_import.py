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


def upload(client, entity, sid, data_rows, ncols=8, create_accounts=False,
           update_existing=False):
    content = make_xlsx(data_rows, ncols)
    url = f"/api/import/{entity}?semester_id={sid}"
    if create_accounts:
        url += "&create_accounts=true"
    if update_existing:
        url += "&update_existing=true"
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
    assert r.json() == {"imported": 2, "updated": 0, "errors": []}
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


# ── 以匯入批次更新既有教師(使用者回報 #18)────────────────
# 欄序:姓名/末四碼/任教科目/基本鐘點/行政職稱/行政減課/外聘/登入帳號/Email/手機/LINE
def _teacher_row(name, id4, subj="", base="", title="", reduction="", external="", acc="",
                 email="", phone="", line=""):
    return [name, id4, subj, base, title, reduction, external, acc, email, phone, line]


def _seed_wang(client, sid):
    """系統裡既有的王小明:教學組長、減課 4、鐘點 20、教數學。"""
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "數學"})
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "物理"})
    rows = [_teacher_row("王小明", "1234", "數學", 20, "教學組長", 4, "否", "", "w@a.edu.tw")]
    assert upload(client, "teachers", sid, rows, ncols=11).json()["imported"] == 1
    return next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")


def test_import_teachers_updates_existing_when_opted_in(scheduler_env):
    """新學年職務異動:同一份名冊再匯入一次,既有教師改為更新而不是報錯。"""
    client, sid = scheduler_env
    before = _seed_wang(client, sid)

    rows = [
        # 王小明卸任組長、鐘點改 22、加教物理;空白的 Email 不應被洗掉
        _teacher_row("王小明", "1234", "數學、物理", 22, "無", 0, "", "", ""),
        _teacher_row("李小華", "5678", "數學", 18),  # 新人照舊新增
    ]
    body = upload(client, "teachers", sid, rows, ncols=11, update_existing=True).json()
    assert body == {"imported": 1, "updated": 1, "errors": []}

    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    assert len(teachers) == 2
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert wang["id"] == before["id"]              # 是更新,不是新建一筆
    assert wang["admin_title"] in (None, "")        # 「無」= 卸任
    assert (wang["base_periods"], wang["admin_reduction"]) == (22, 0)
    assert {s["name"] for s in wang["subjects"]} == {"數學", "物理"}
    assert wang["email"] == "w@a.edu.tw"            # 空白欄位保留原值


def test_import_teachers_blank_cells_keep_existing_values(scheduler_env):
    """只想改行政職稱時,其他欄位留空不該被清掉。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", "", "輔導主任")]
    assert upload(client, "teachers", sid, rows, ncols=11,
                  update_existing=True).json()["updated"] == 1
    wang = next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")
    assert wang["admin_title"] == "輔導主任"
    assert (wang["base_periods"], wang["admin_reduction"]) == (20, 4)
    assert {s["name"] for s in wang["subjects"]} == {"數學"}
    assert wang["email"] == "w@a.edu.tw"


def test_import_teachers_without_opt_in_still_rejects_duplicates(scheduler_env):
    """沒有勾選更新時維持原行為:既有教師視為重複、整批不寫入。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", 22)]
    body = upload(client, "teachers", sid, rows, ncols=11).json()
    assert body["imported"] == 0 and body["updated"] == 0
    assert any("重複" in e for e in body["errors"])
    wang = next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")
    assert wang["base_periods"] == 20  # 未被更動


def test_import_teachers_update_mode_still_rejects_duplicate_rows(scheduler_env):
    """同一個檔案裡出現兩次同一位老師仍是錯誤(不知道該聽哪一列)。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", 22), _teacher_row("王小明", "1234", "", 24)]
    body = upload(client, "teachers", sid, rows, ncols=11, update_existing=True).json()
    assert body["updated"] == 0
    assert any("重複" in e for e in body["errors"])


def test_import_teachers_update_does_not_touch_login_account(scheduler_env):
    """既有教師的登入帳號不在匯入時建立(避免誤建);新教師仍可建立。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [
        _teacher_row("王小明", "1234", "", 22, "", "", "", "wang001"),
        _teacher_row("陳小美", "9999", "數學", 18, "", "", "", "chen001"),
    ]
    body = upload(client, "teachers", sid, rows, ncols=11,
                  create_accounts=True, update_existing=True).json()
    assert body == {"imported": 1, "updated": 1, "errors": []}
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    chen = next(t for t in teachers if t["name"] == "陳小美")
    assert wang["user_id"] is None      # 既有教師不會被偷建帳號
    assert chen["user_id"] is not None  # 新教師照舊


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
