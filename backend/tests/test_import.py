"""Excel 匯入測試。對應 M1-3 驗收標準。"""

import io

import pytest
from openpyxl import Workbook, load_workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role
from app.services import importer
from tests.conftest import make_user
from tests.creds import PW


@pytest.fixture
def scheduler_env(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    return client, sem["id"]


EXAMPLE_NOTE = "第 3 列是範本的範例,已略過(如果這一列是要匯入的資料,請改到下一列)。"


def make_xlsx(entity: str, data_rows: list[list]) -> bytes:
    """真正的範本(欄名/說明/範例三列)+ 資料列。"""
    wb = load_workbook(io.BytesIO(importer.build_template(entity)))
    ws = wb.active
    for r in data_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, entity, sid, data_rows, ncols=8, create_accounts=False,
           update_existing=False):
    content = make_xlsx(entity, data_rows)
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
    assert r.json() == {"imported": 2, "updated": 0, "errors": [], "accounts": [],
                        "notes": [EXAMPLE_NOTE]}
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
    # 帳號已建立,每位老師各有一組系統產生的初始密碼(v1.6.0),可登入但首登需改密
    accounts = {a["username"]: a for a in r.json()["accounts"]}
    assert set(accounts) == {"wang001", "lee001"}
    assert accounts["wang001"]["name"] == "王小明"
    assert accounts["wang001"]["password"] != accounts["lee001"]["password"]
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={
        "username": "wang001", "password": accounts["wang001"]["password"]})
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
    assert {k: body[k] for k in ("imported", "updated", "errors")} == {
        "imported": 1, "updated": 1, "errors": []}

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
    assert {k: body[k] for k in ("imported", "updated", "errors")} == {
        "imported": 1, "updated": 1, "errors": []}
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


# ── 第 2、3 列(v1.7.2 組長回報:第一筆資料打在範例列上就默默不見了)────────
def _sheet(rows: list[list]) -> bytes:
    """自己決定每一列的內容(不套範本),模擬組長改過的檔案。"""
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(client, entity, sid, content):
    return client.post(f"/api/import/{entity}?semester_id={sid}",
                       files={"file": ("t.xlsx", content, XLSX_MIME)}).json()


def _template_rows(entity: str) -> tuple[list, list, list]:
    cols = importer.TEMPLATE_DEFS[entity]["columns"]
    return [c[0] for c in cols], [c[1] for c in cols], [c[2] for c in cols]


def test_data_typed_on_the_example_row_is_imported(scheduler_env):
    """把範例列改成自己的資料(組長的做法):第 3 列照常匯入,不再默默略過。"""
    client, sid = scheduler_env
    head, desc, _ = _template_rows("classes")
    content = _sheet([head, desc, [1, "一年一班", "國中"], [1, "一年二班", "國中"]])
    r = _post(client, "classes", sid, content)
    assert (r["imported"], r["errors"], r["notes"]) == (2, [], [])
    names = {c["name"] for c in client.get(f"/api/class-units?semester_id={sid}").json()}
    assert names == {"一年一班", "一年二班"}


def test_rows_right_after_the_header_are_imported(scheduler_env):
    """刪掉說明列與範例列,資料從第 2 列開始:每一列都要匯入。"""
    client, sid = scheduler_env
    head, _, _ = _template_rows("subjects")
    r = _post(client, "subjects", sid, _sheet([head, ["國文"], ["英語"], ["數學"]]))
    assert (r["imported"], r["errors"]) == (3, [])


def test_deleted_description_row_still_skips_the_example(scheduler_env):
    """只刪說明列:範例移到第 2 列,仍當範例略過,並告訴組長。"""
    client, sid = scheduler_env
    head, _, example = _template_rows("subjects")
    r = _post(client, "subjects", sid, _sheet([head, example, ["國文"]]))
    assert (r["imported"], r["errors"]) == (1, [])
    assert r["notes"] == ["第 2 列是範本的範例,已略過(如果這一列是要匯入的資料,請改到下一列)。"]


def test_old_teacher_template_description_row_is_still_skipped(scheduler_env):
    """v1.2.8 以前的教師範本,說明列有兩格文字不同:以「必填」開頭就認得是說明列。"""
    client, sid = scheduler_env
    head, desc, example = _template_rows("teachers")
    old_desc = [d.split(";")[0] for d in desc]   # 舊範本沒有「;更新…」那段
    r = _post(client, "teachers", sid, _sheet([head, old_desc, example, ["林老師"]]))
    assert (r["imported"], r["errors"]) == (1, [])
    names = [t["name"] for t in client.get(f"/api/teachers?semester_id={sid}").json()]
    assert names == ["林老師"]
